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

// Lending Settings' theme preview opens a page with this flag; see lending/portal/preview.py.
const PREVIEW_PARAM = "lending_preview"
const inPreview =
	typeof window !== "undefined" && new URLSearchParams(window.location.search).get(PREVIEW_PARAM) === "1"
const guardedRouters = new WeakSet()

// The pages preview.py fills with the made-up borrower; any other would show the admin's own.
const PREVIEW_PAGES = ["/overview", "/loans", "/applications", "/statement", "/certificate", "/profile"]

function previewable(path: string): boolean {
	return PREVIEW_PAGES.includes(path) || path.startsWith("/loan/") || path.startsWith("/application/")
}

// Keeps the flag on every in-app move, since the server reads it from the page's URL.
export function guardPreview(router: any) {
	if (!inPreview || guardedRouters.has(router)) return
	guardedRouters.add(router)

	router.beforeEach((to: any) => {
		if (!previewable(to.path)) return false
		if (to.query[PREVIEW_PARAM] !== "1") {
			return { path: to.path, hash: to.hash, query: { ...to.query, [PREVIEW_PARAM]: "1" } }
		}
	})
}

// A full load, not router.push: open pages would keep what they read before logout.
export async function logout(router: any) {
	await call("logout")
	window.location.href = router.resolve("/apply").href
}

export function resendLabel(seconds: number): string {
	return `Resend in 00:${String(seconds).padStart(2, "0")}`
}

const APPEARANCE_URL = "lending.portal.theme.set_appearance"
const APPEARANCES = [
	{ value: "light", label: "Light", icon: "lucide-sun" },
	{ value: "dark", label: "Dark", icon: "lucide-moon" },
	{ value: "system", label: "System", icon: "lucide-monitor" },
]

// lending.portal.theme marks <html> with the choice; the Studio canvas has neither.
const darkQuery = typeof window === "undefined" ? null : window.matchMedia("(prefers-color-scheme: dark)")

function applyAppearance(choice: string) {
	const root = document.documentElement
	root.dataset.appearance = choice
	root.dataset.theme = choice === "system" ? (darkQuery?.matches ? "dark" : "light") : choice
}

darkQuery?.addEventListener("change", () => {
	if (document.documentElement.dataset.appearance === "system") applyAppearance("system")
})

// SidebarItem's own match compares route names, which misses detail pages like /loan/:name.
export function useMenus(route: any, open: (url?: string) => void, logout: () => void) {
	const isActive = (to: string, prefix?: string) =>
		route.path === to || Boolean(prefix && route.path.startsWith(prefix))

	const appearance = ref(typeof document === "undefined" ? "" : document.documentElement.dataset.appearance || "")
	const chooseAppearance = (choice: string) => {
		appearance.value = choice
		applyAppearance(choice)
		call(APPEARANCE_URL, { appearance: choice })
	}

	const accountMenu = (canSwitch?: boolean) => [
		...(canSwitch
			? [{ label: "Switch account", icon: "lucide-arrow-left-right", onClick: () => open("/accounts") }]
			: []),
		// The preview runs in the admin's Desk session: these would act on the admin.
		...(inPreview
			? []
			: [
					{
						label: "Appearance",
						icon: "lucide-sun-moon",
						submenu: APPEARANCES.map(({ value, label, icon }) => ({
							label,
							icon,
							selected: appearance.value === value,
							onClick: () => chooseAppearance(value),
						})),
					},
					{ label: "Log out", icon: "lucide-log-out", onClick: logout },
				]),
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
	// The theme preview has nothing worth searching: its borrower is made up.
	if (!inPreview && !window.location.pathname.startsWith("/studio")) {
		window.addEventListener("keydown", onKeydown)
	}
	onScopeDispose(() => {
		window.removeEventListener("keydown", onKeydown)
		clearTimeout(timer)
	})

	return { showSearch, searchText, searchResults, searchNote, searchIndex, chooseResult }
}
