// Shared by every page's setup() module, as "@app/utils/portal".

import { onScopeDispose, ref, watch } from "vue"
import { call } from "frappe-ui"

const TONES: Record<string, string> = { info: "blue", ok: "green", warn: "orange", danger: "red" }

/** A payload tone -- "", "info", "ok", "warn", "danger" -- as a frappe-ui Badge theme. */
export function tone(value?: string): string {
	return TONES[value || ""] || "gray"
}

// A portal URL from the data layer as this app's own route.
//
// Every endpoint answers with the Builder portal's paths -- "/borrower/loan/L-0001" --
// because the Builder pages still serve them. The data layer is shared and is not
// forked for this app, so the prefix comes off here instead.
//
// Line comments rather than a JSDoc block: a continuation line of one begins with a
// space, and pycodestyle takes the first space-indented line in a file as its indent
// character -- after which every tab in this tab-indented module reads as E117.
export function appRoute(url?: string): string {
	if (!url) return ""
	return url.replace(/^\/borrower(-portal)?/, "") || "/overview"
}

// Ends the session and lands on the apply page, the one page a guest can use.
//
// A full load rather than router.push: the session and its CSRF token are gone, and
// every page already open would otherwise keep what it read as the borrower.
export async function logout(router: any) {
	await call("logout")
	window.location.href = router.resolve("/apply").href
}

const FIND_URL = "/api/method/lending.portal.search.find"

// The command palette behind Ctrl+K, as the desk's own awesomebar opens: the same
// shortcut on every page, arrows to move, Enter to go. The dialog is the shell's
// borrower_search component; everything it reads is returned from here.
//
// The results are fetched here rather than through a page data source. A source
// re-fetches the moment its parameters change, with nothing to hold it back while the
// borrower is still typing, and every page would have to declare one. `asked` drops an
// answer that arrives after a newer question was sent.
//
// A GET, because find() reads and changes nothing.
export function useSearch(open: (url?: string) => void) {
	const showSearch = ref(false)
	const searchText = ref("")
	const searchResults = ref<any[]>([])
	const searchNote = ref("")
	const searchIndex = ref(0)
	let asked = 0
	let timer: ReturnType<typeof setTimeout> | undefined

	async function find(query: string) {
		const ticket = ++asked
		const response = await fetch(`${FIND_URL}?q=${encodeURIComponent(query)}`, {
			headers: { Accept: "application/json" },
		})
		if (ticket !== asked || !response.ok) return

		const { message } = await response.json()
		searchResults.value = message.results
		searchNote.value = message.note
		searchIndex.value = 0
	}

	watch(searchText, (query) => {
		clearTimeout(timer)
		timer = setTimeout(() => find(query.trim()), 150)
	})

	// Every opening starts from an empty box, which answers with the portal's own pages.
	watch(showSearch, (shown) => {
		if (!shown) return
		searchText.value = ""
		find("")
	})

	function chooseResult(item?: { url?: string }) {
		if (!item) return
		showSearch.value = false
		open(item.url)
	}

	function move(step: number) {
		const count = searchResults.value.length
		if (count) searchIndex.value = (searchIndex.value + step + count) % count
	}

	function onKeydown(event: KeyboardEvent) {
		if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
			event.preventDefault()
			showSearch.value = !showSearch.value
			return
		}
		if (!showSearch.value || event.isComposing) return

		if (event.key === "ArrowDown" || event.key === "ArrowUp") {
			event.preventDefault()
			move(event.key === "ArrowDown" ? 1 : -1)
		} else if (event.key === "Enter") {
			event.preventDefault()
			chooseResult(searchResults.value[searchIndex.value])
		}
	}

	// Studio's editor has a Ctrl+K of its own, and runs a page's setup() on its canvas.
	if (!window.location.pathname.startsWith("/studio")) {
		window.addEventListener("keydown", onKeydown)
	}
	onScopeDispose(() => {
		window.removeEventListener("keydown", onKeydown)
		clearTimeout(timer)
	})

	return { showSearch, searchText, searchResults, searchNote, searchIndex, chooseResult }
}
