import { computed, ref, watch } from "vue"
import { call, toast } from "frappe-ui"
import { tone, appRoute, logout as endSession, useSearch, useMenus } from "@app/utils/portal"

export default function setup(context: any) {
	const { router } = context
	const showAlerts = ref(false)
	const alertsTab = ref("attention")
	const sidebarCollapsed = ref<boolean | null>(null)

	const open = (url?: string) => {
		const to = appRoute(url)
		if (to) router.push(to)
	}
	const logout = () => endSession(router)
	const search = useSearch(open)
	const menus = useMenus(context.route, open, logout)

	watch(
		() => context.overview?.data?.choose_account,
		(choose) => { if (choose) router.replace("/accounts") },
		{ immediate: true },
	)

	const applicationDot = computed(() => {
		const data = context.overview?.data
		if (!data?.application_stage) return ""
		return data.application_stage_tone === "warn" ? "orange" : "green"
	})

	return { tone, open, logout, showAlerts, alertsTab, sidebarCollapsed, ...search, ...menus, applicationDot }
}
