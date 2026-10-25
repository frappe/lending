import { computed, ref, watch } from "vue"
import { call, toast } from "frappe-ui"
import { tone, appRoute, logout as endSession } from "@app/utils/portal"

export default function setup(context: any) {
	const { router } = context
	const showAlerts = ref(false)
	const alertsTab = ref("attention")
	const sidebarCollapsed = ref<boolean | null>(null)
	const reference = ref("")
	const mobileNumber = ref("")

	const open = (url?: string) => {
		const to = appRoute(url)
		if (to) router.push(to)
	}
	const logout = () => endSession(router)

	const busy = ref(false)
	const result = ref<Record<string, any>>({})

	const find = () => {
		busy.value = true
		call("lending.portal.apply.track_application", {
			reference: reference.value,
			mobile_number: mobileNumber.value,
		})
			.then((payload: any) => { result.value = payload })
			.catch((error: any) =>
				toast.error(String(error?.messages?.[0] || error?.message || error)),
			)
			.finally(() => { busy.value = false })
	}

	const startOver = () => { result.value = {} }

	return { tone, open, logout, showAlerts, alertsTab, sidebarCollapsed, reference, mobileNumber, busy, result, find, startOver }
}
