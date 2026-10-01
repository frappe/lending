import { computed, ref, watch } from "vue"
import { call, toast } from "frappe-ui"
import { tone, appRoute, logout as endSession, useSearch } from "@app/utils/portal"

export default function setup(context: any) {
	const { router } = context
	const showAlerts = ref(false)
	const alertsTab = ref("attention")
	const sidebarCollapsed = ref<boolean | null>(null)
	const year = ref(currentYear())

	const open = (url?: string) => {
		const to = appRoute(url)
		if (to) router.push(to)
	}
	const logout = () => endSession(router)
	const search = useSearch(open)

	function currentYear() {
		const today = new Date()
		const start = today.getFullYear() - (today.getMonth() < 3 ? 1 : 0)
		return `${start}-${start + 1}`
	}

	return { tone, open, logout, showAlerts, alertsTab, sidebarCollapsed, ...search, year }
}
