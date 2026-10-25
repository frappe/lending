import { computed, ref, watch } from "vue"
import { call, toast } from "frappe-ui"
import { tone, appRoute, logout as endSession } from "@app/utils/portal"

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

	const busy = ref(false)
	const allow = () => {
		busy.value = true
		call("lending.portal.secured.give_kyc_consent")
			.then((result: any) => {
				if (result?.ok === false) { toast.error(result.message); return }
				router.push(result.redirect)
			})
			.catch((error: any) => toast.error(String(error?.messages?.[0] || error)))
			.finally(() => { busy.value = false })
	}
	const decline = () => router.push("/secured-loan")

	return { tone, open, logout, showAlerts, alertsTab, sidebarCollapsed, busy, allow, decline }
}
