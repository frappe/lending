import { computed, ref, watch } from "vue"
import { call, toast } from "frappe-ui"
import { tone, appRoute, logout as endSession, useSearch } from "@app/utils/portal"

export default function setup(context: any) {
	const { router } = context
	const showAlerts = ref(false)
	const alertsTab = ref("attention")
	const sidebarCollapsed = ref<boolean | null>(null)
	const fromDate = ref(isoDay(yearStart()))
	const toDate = ref(isoDay(new Date()))

	const open = (url?: string) => {
		const to = appRoute(url)
		if (to) router.push(to)
	}
	const logout = () => endSession(router)
	const search = useSearch(open)

	function isoDay(day: Date) {
		const pad = (n: number) => String(n).padStart(2, "0")
		return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`
	}

	function yearStart(yearsBack = 0) {
		const today = new Date()
		const start = today.getFullYear() - (today.getMonth() < 3 ? 1 : 0) - yearsBack
		return new Date(start, 3, 1)
	}

	const setPeriod = (period: string) => {
		const today = new Date()
		if (period === "last_year") {
			const start = yearStart(1)
			fromDate.value = isoDay(start)
			toDate.value = isoDay(new Date(start.getFullYear() + 1, 2, 31))
		} else if (period === "last_quarter") {
			fromDate.value = isoDay(new Date(today.getFullYear(), today.getMonth() - 3, today.getDate()))
			toDate.value = isoDay(today)
		} else {
			fromDate.value = isoDay(yearStart())
			toDate.value = isoDay(today)
		}
	}

	return { tone, open, logout, showAlerts, alertsTab, sidebarCollapsed, ...search, fromDate, toDate, setPeriod }
}
