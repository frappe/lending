import { computed, ref, watch } from "vue"
import { call, toast } from "frappe-ui"
import { tone, appRoute, logout as endSession, useSearch } from "@app/utils/portal"

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

	const choosing = ref("")

	const chooseAccount = (name: string) => {
		if (choosing.value) return
		choosing.value = name
		call("lending.portal.switcher.choose_account", { name })
			.then((result: any) => open(result?.url))
			.catch((error: any) =>
				toast.error(String(error?.messages?.[0] || error?.message || error)),
			)
			.finally(() => { choosing.value = "" })
	}

	return { tone, open, logout, showAlerts, alertsTab, sidebarCollapsed, ...search, choosing, chooseAccount }
}
