import { onScopeDispose, ref, watch } from "vue"
import { call } from "frappe-ui"

const TONES: Record<string, string> = { info: "blue", ok: "green", warn: "orange", danger: "red" }

export function tone(value?: string): string {
	return TONES[value || ""] || "gray"
}

// The shared endpoints still return /borrower/* paths, so the prefix comes off here.
export function appRoute(url?: string): string {
	if (!url) return ""
	return url.replace(/^\/borrower(-portal)?/, "") || "/overview"
}

// A full load, not router.push: open pages would keep what they read before logout.
export async function logout(router: any) {
	await call("logout")
	window.location.href = router.resolve("/apply").href
}

export function resendLabel(seconds: number): string {
	return `Resend in 00:${String(seconds).padStart(2, "0")}`
}

// SidebarItem's own match compares route names, which misses detail pages like /loan/:name.
export function useMenus(route: any, open: (url?: string) => void, logout: () => void) {
	const isActive = (to: string, prefix?: string) =>
		route.path === to || Boolean(prefix && route.path.startsWith(prefix))

	const accountMenu = (canSwitch?: boolean) => [
		...(canSwitch
			? [{ label: "Switch account", icon: "lucide-arrow-left-right", onClick: () => open("/accounts") }]
			: []),
		{ label: "Log out", icon: "lucide-log-out", onClick: logout },
	]

	return { isActive, accountMenu }
}

const FIND_URL = "/api/method/lending.portal.search.find"

// Not a page data source: that refetches on every keystroke; `asked` drops stale answers.
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
