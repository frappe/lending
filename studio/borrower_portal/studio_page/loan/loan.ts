import { computed, ref, watch } from "vue"
import { call, toast } from "frappe-ui"
import { tone, appRoute, logout as endSession, useSearch } from "@app/utils/portal"

export default function setup(context: any) {
	const { router } = context
	const showAlerts = ref(false)
	const alertsTab = ref("attention")
	const sidebarCollapsed = ref<boolean | null>(null)
	const requestOpen = ref(false)
	const requestAmount = ref("")

	const open = (url?: string) => {
		const to = appRoute(url)
		if (to) router.push(to)
	}
	const logout = () => endSession(router)
	const search = useSearch(open)

	const requesting = ref(false)

	const openRequest = () => {
		requestAmount.value = ""
		requestOpen.value = true
	}

	const sendRequest = () => {
		requesting.value = true
		call("lending.portal.loans.request_disbursement", {
			name: context.loan.data?.drawdown?.loan,
			amount: requestAmount.value,
		})
			.then((result: any) => {
				toast.success(result?.message || "We have your request.")
				requestOpen.value = false
				context.loan.reload()
			})
			.catch((error: any) =>
				toast.error(String(error?.messages?.[0] || error?.message || error)),
			)
			.finally(() => { requesting.value = false })
	}

	return { tone, open, logout, showAlerts, alertsTab, sidebarCollapsed, ...search, requestOpen, requestAmount, requesting, openRequest, sendRequest }
}
