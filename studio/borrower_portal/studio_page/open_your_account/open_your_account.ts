import { computed, ref, watch } from "vue"
import { call, toast } from "frappe-ui"
import { tone, appRoute, logout as endSession } from "@app/utils/portal"

export default function setup(context: any) {
	const { router } = context
	const showAlerts = ref(false)
	const alertsTab = ref("attention")
	const sidebarCollapsed = ref<boolean | null>(null)
	const mobileNumber = ref("")
	const otp = ref("")
	const fullName = ref("")
	const email = ref("")

	const open = (url?: string) => {
		const to = appRoute(url)
		if (to) router.push(to)
	}
	const logout = () => endSession(router)

	const busy = ref(false)
	const token = ref("")
	const codeSent = ref(false)
	const fail = (error: any) => toast.error(String(error?.messages?.[0] || error?.message || error))
	const sendCode = () => {
		busy.value = true
		call("lending.portal.apply.send_mobile_code", { mobile_number: mobileNumber.value })
			.then((result: any) => { codeSent.value = true; toast.success(result.message) })
			.catch(fail)
			.finally(() => { busy.value = false })
	}
	const confirmCode = () => {
		busy.value = true
		call("lending.portal.apply.confirm_mobile_code", { mobile_number: mobileNumber.value, otp: otp.value })
			.then((result: any) => {
				if (!result.verified) { toast.error(result.message); return }
				token.value = result.token
			})
			.catch(fail)
			.finally(() => { busy.value = false })
	}
	// Not `register`: a setup() binding shadows the data source of the same name.
	const openAccount = () => {
		busy.value = true
		call("lending.portal.secured.register", { token: token.value, full_name: fullName.value, email: email.value })
			.then((result: any) => { window.location.href = router.resolve(result.redirect).href })
			.catch(fail)
			.finally(() => { busy.value = false })
	}

	return { tone, open, logout, showAlerts, alertsTab, sidebarCollapsed, mobileNumber, otp, fullName, email, busy, token, codeSent, sendCode, confirmCode, openAccount }
}
