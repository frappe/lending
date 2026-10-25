import { computed, ref, watch } from "vue"
import { call, toast } from "frappe-ui"
import { tone, appRoute, logout as endSession, resendLabel } from "@app/utils/portal"

export default function setup(context: any) {
	const { router } = context
	const showAlerts = ref(false)
	const alertsTab = ref("attention")
	const sidebarCollapsed = ref<boolean | null>(null)
	const email = ref("")
	const otp = ref("")

	const open = (url?: string) => {
		const to = appRoute(url)
		if (to) router.push(to)
	}
	const logout = () => endSession(router)

	const busy = ref(false)
	const codeSent = ref(false)
	const sentNote = ref("")
	const sentHint = ref("")
	const resendIn = ref(0)
	let timer: ReturnType<typeof setInterval> | undefined

	// Same rule as login.portal_redirect: a link can't send a borrower off the portal.
	const redirectTo = () => {
		const to = String(context.route.query["redirect-to"] || "")
		return to.startsWith(router.resolve("/").href) ? to : router.resolve("/overview").href
	}

	// Studio's editor runs setup() on its canvas, where the editor is never a guest.
	if (!window.is_guest && !window.location.pathname.startsWith("/studio")) {
		window.location.replace(redirectTo())
	}

	const fail = (error: any) =>
		toast.error(String(error?.messages?.[0] || error?.message || error))

	const countDown = () => {
		clearInterval(timer)
		resendIn.value = 30
		timer = setInterval(() => {
			if (--resendIn.value <= 0) clearInterval(timer)
		}, 1000)
	}

	const sendCode = () => {
		if (busy.value) return
		busy.value = true
		call("lending.portal.login.send_login_code", { email: email.value })
			.then((result: any) => {
				if (!result.sent) {
					toast.error(result.message)
					open(result.apply_url)
					return
				}
				codeSent.value = true
				sentNote.value = result.message
				sentHint.value = result.hint
				otp.value = ""
				countDown()
			})
			.catch(fail)
			.finally(() => { busy.value = false })
	}

	const resendCode = () => {
		if (resendIn.value > 0) return
		sendCode()
	}

	const verifyCode = () => {
		if (busy.value) return
		busy.value = true
		call("lending.portal.login.verify_login_code", {
			email: email.value,
			otp: otp.value,
			redirect_to: redirectTo(),
		})
			.then((result: any) => {
				if (!result.verified) {
					toast.error(result.message)
					busy.value = false
					return
				}
				// A full load: the app booted as a guest and holds no borrower pages yet.
				window.location.href = result.redirect_to
			})
			.catch((error: any) => {
				fail(error)
				busy.value = false
			})
	}

	const changeEmail = () => {
		clearInterval(timer)
		codeSent.value = false
		otp.value = ""
		resendIn.value = 0
	}

	const withGoogle = (url?: string) => {
		if (url) window.location.href = url
	}

	return { tone, open, logout, showAlerts, alertsTab, sidebarCollapsed, email, otp, resendLabel, busy, codeSent, sentNote, sentHint, resendIn, sendCode, resendCode, verifyCode, changeEmail, withGoogle }
}
