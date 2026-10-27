import { computed, ref, watch } from "vue"
import { call, toast } from "frappe-ui"
import { tone, appRoute, logout as endSession, useSearch, useMenus, guardPreview } from "@app/utils/portal"

export default function setup(context: any) {
	const { router } = context
	const showAlerts = ref(false)
	const alertsTab = ref("attention")
	const sidebarCollapsed = ref<boolean | null>(null)
	const previewTab = ref("terms")

	const open = (url?: string) => {
		const to = appRoute(url)
		if (to) router.push(to)
	}
	const logout = () => endSession(router)
	guardPreview(router)
	const search = useSearch(open)
	const menus = useMenus(context.route, open, logout)

	return { tone, open, logout, showAlerts, alertsTab, sidebarCollapsed, ...search, ...menus, previewTab }
}
