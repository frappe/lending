import { computed, ref, watch } from "vue"
import { call, toast } from "frappe-ui"
import { tone, appRoute, logout as endSession, resendLabel } from "@app/utils/portal"

export default function setup(context: any) {
	const { router } = context
	const showAlerts = ref(false)
	const alertsTab = ref("attention")
	const sidebarCollapsed = ref<boolean | null>(null)
	const step = ref(1)
	const applicantType = ref("Individual")
	const loanProduct = ref("")
	const mobileNumber = ref("")
	const otp = ref("")
	const employmentType = ref("Salaried")
	const accountOtp = ref("")
	const accountCodeSent = ref(false)
	const accountNote = ref("")
	const companyName = ref("")
	const applicantName = ref("")
	const dateOfBirth = ref("")
	const pan = ref("")
	const applicantCountry = ref("")
	const email = ref("")
	const loanAmount = ref("")
	const proposedTenure = ref("")
	const income = ref("")

	const open = (url?: string) => {
		const to = appRoute(url)
		if (to) router.push(to)
	}
	const logout = () => endSession(router)

	const busy = ref(false)
	const codeSent = ref(false)
	const token = ref("")
	const accountToken = ref("")
	const offer = ref<Record<string, any>>({})

	// Step 1 is the landing screen, so the count starts at step 2.
	const stepNames = ["Who is borrowing", "What you need", "Your mobile number", "Your details", "Your offer", "Your account"]
	const stepLabel = computed(() => `Step ${step.value - 1} of ${stepNames.length} · ${stepNames[step.value - 2] || ""}`)
	const stepProgress = computed(() => ((step.value - 1) / stepNames.length) * 100)

	const fail = (error: any) =>
		toast.error(String(error?.messages?.[0] || error?.message || error))

	// Once the number is confirmed, step over the mobile screen in either direction.
	const go = (to: number) => {
		if (to === 4 && token.value) to = step.value > 4 ? 3 : 5
		step.value = to
	}

	const choose = (type: string) => {
		if (type !== applicantType.value) loanProduct.value = ""
		applicantType.value = type
	}

	const chooseProduct = (product: string) => { loanProduct.value = product }

	const resendIn = ref(0)
	const countDown = () => {
		resendIn.value = 30
		const timer = setInterval(() => {
			if (--resendIn.value <= 0) clearInterval(timer)
		}, 1000)
	}

	const sendCode = () => {
		busy.value = true
		call("lending.portal.apply.send_mobile_code", { mobile_number: mobileNumber.value })
			.then((result: any) => {
				codeSent.value = true
				countDown()
				toast.success(result.message)
			})
			.catch(fail)
			.finally(() => { busy.value = false })
	}

	const resendCode = () => {
		if (resendIn.value > 0 || busy.value) return
		sendCode()
	}

	const confirmCode = () => {
		busy.value = true
		call("lending.portal.apply.confirm_mobile_code", {
			mobile_number: mobileNumber.value,
			otp: otp.value,
		})
			.then((result: any) => {
				if (!result.verified) { toast.error(result.message); return }
				token.value = result.token
				step.value = 5
			})
			.catch(fail)
			.finally(() => { busy.value = false })
	}

	const submit = () => {
		busy.value = true
		call("lending.portal.apply.submit_lead", {
			token: token.value,
			applicant_type: applicantType.value,
			loan_product: loanProduct.value,
			company_name: companyName.value,
			applicant_name: applicantName.value,
			date_of_birth: dateOfBirth.value,
			pan: pan.value,
			applicant_country: applicantCountry.value,
			email: email.value,
			loan_amount: loanAmount.value,
			proposed_tenure: proposedTenure.value,
			income: income.value,
			employment_type: employmentType.value,
		})
			.then((result: any) => {
				offer.value = result
				accountToken.value = result.account_token
				step.value = 6
			})
			.catch((error: any) => {
				fail(error)
				if (error?.exc_type !== "VerificationExpiredError") return
				token.value = ""
				codeSent.value = false
				otp.value = ""
				step.value = 4
			})
			.finally(() => { busy.value = false })
	}

	const sendAccountCode = () => {
		if (busy.value) return
		busy.value = true
		call("lending.portal.apply.send_account_code", { token: accountToken.value, email: email.value })
			.then((result: any) => {
				accountCodeSent.value = true
				accountNote.value = result.message
				accountOtp.value = ""
				countDown()
			})
			.catch(fail)
			.finally(() => { busy.value = false })
	}

	const resendAccountCode = () => {
		if (resendIn.value > 0) return
		sendAccountCode()
	}

	const changeAccountEmail = () => {
		accountCodeSent.value = false
		accountOtp.value = ""
	}

	const createAccount = () => {
		busy.value = true
		call("lending.portal.apply.create_account", {
			token: accountToken.value,
			email: email.value,
			otp: accountOtp.value,
		})
			.then((result: any) => {
				if (!result.verified) { toast.error(result.message); return }
				window.location.href = router.resolve("/overview").href
			})
			.catch(fail)
			.finally(() => { busy.value = false })
	}

	return { tone, open, logout, showAlerts, alertsTab, sidebarCollapsed, step, applicantType, loanProduct, mobileNumber, otp, employmentType, accountOtp, accountCodeSent, accountNote, companyName, applicantName, dateOfBirth, pan, applicantCountry, email, loanAmount, proposedTenure, income, resendLabel, busy, codeSent, offer, stepLabel, stepProgress, go, choose, chooseProduct, sendCode, resendIn, resendCode, confirmCode, submit, sendAccountCode, resendAccountCode, changeAccountEmail, createAccount }
}
