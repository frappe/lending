import { computed, ref, watch } from "vue"
import { call, toast } from "frappe-ui"
import { tone, appRoute, logout as endSession, useSearch, useMenus } from "@app/utils/portal"

export default function setup(context: any) {
	const { router } = context
	const showAlerts = ref(false)
	const alertsTab = ref("attention")
	const sidebarCollapsed = ref<boolean | null>(null)
	const pan = ref("")
	const collateral = ref("Mutual Funds")
	const holdingsRequest = ref("")
	const holdingsOtp = ref("")
	const notApproved = ref([])
	const chosen = ref([] as string[])
	const loanAmount = ref("")
	const tenure = ref("12")
	const pledgeOtp = ref("")
	const pledgeSent = ref(false)
	const accountNumber = ref("")
	const ifsc = ref("")
	const esignOtp = ref("")
	const esignSent = ref(false)

	const open = (url?: string) => {
		const to = appRoute(url)
		if (to) router.push(to)
	}
	const logout = () => endSession(router)
	const search = useSearch(open)
	const menus = useMenus(context.route, open, logout)

	const page = computed<any>(() => context.securedLoan.data || {})
	const busy = ref(false)
	const viewing = ref("")
	const shown = computed(() => viewing.value || page.value.current || "")

	const fail = (error: any) => toast.error(String(error?.messages?.[0] || error?.message || error))
	// Endpoints answer a provider's refusal with ok: false, so the logged attempt is kept.
	const run = (method: string, args: Record<string, any>, then?: (result: any) => void) => {
		busy.value = true
		return call(`lending.portal.secured.${method}`, args)
			.then((result: any) => {
				if (result?.ok === false) { toast.error(result.message); return }
				if (result?.message) toast.success(result.message)
				then?.(result)
			})
			.catch(fail)
			.finally(() => { busy.value = false })
	}
	const advance = () => {
		viewing.value = ""
		context.securedLoan.reload()
	}
	const viewStep = (row: any) => {
		if (row.state !== "todo") viewing.value = row.key === page.value.current ? "" : row.key
	}

	const money = (amount: number) =>
		new Intl.NumberFormat("en-IN", { style: "currency", currency: page.value.currency || "INR", maximumFractionDigits: 0 }).format(amount || 0)

	const verifyPan = () => run("verify_pan", { pan: pan.value }, advance)

	const sendHoldingsOtp = () =>
		run("send_holdings_otp", { collateral: collateral.value }, (result) => { holdingsRequest.value = result.request_id })
	const fetchHoldings = () =>
		run("fetch_holdings", { collateral: collateral.value, request_id: holdingsRequest.value, otp: holdingsOtp.value }, (result) => {
			notApproved.value = result.not_approved || []
			holdingsRequest.value = ""
			holdingsOtp.value = ""
			advance()
		})
	const refetch = () => { viewing.value = "eligibility" }

	const holdings = computed<any[]>(() => page.value.holdings || [])
	watch(() => page.value.application?.lines, (lines) => {
		if (lines?.length) chosen.value = [...new Set<string>(lines.map((line: any) => line.holding))]
	}, { immediate: true })
	const toggle = (holding: any) => {
		if (sent.value || !holding.pledgeable_units) return
		chosen.value = chosen.value.includes(holding.holding)
			? chosen.value.filter((name) => name !== holding.holding)
			: [...chosen.value, holding.holding]
	}
	const sent = computed(() => Boolean(page.value.application?.sent))
	const chosenEligible = computed(() =>
		holdings.value.filter((row) => chosen.value.includes(row.holding)).reduce((sum, row) => sum + row.eligible, 0))
	const limit = computed(() => {
		const ceiling = page.value.product?.maximum || 0
		return Math.floor(ceiling ? Math.min(chosenEligible.value, ceiling) : chosenEligible.value)
	})
	const useLimit = () => { loanAmount.value = String(limit.value) }
	watch(() => page.value.application?.amount, (amount) => { if (amount) loanAmount.value = String(amount) }, { immediate: true })
	watch(() => page.value.application?.tenure, (months) => { if (months) tenure.value = String(months) }, { immediate: true })
	const canApply = computed(() => chosen.value.length > 0 && Number(loanAmount.value) > 0 && Number(loanAmount.value) <= limit.value)
	const startApplication = () =>
		run("start_application", {
			collateral: collateral.value,
			lines: JSON.stringify(holdings.value.filter((row) => chosen.value.includes(row.holding)).map((row) => ({ holding: row.holding, units: row.pledgeable_units }))),
			loan_amount: loanAmount.value,
			tenure: tenure.value,
		}, advance)

	// A provider's page is another site, so this is a full load, not a router push.
	const startKyc = () => run("start_kyc", {}, (result) => { window.location.href = result.redirect_url })
	const completeKyc = () => run("complete_kyc", {}, advance)
	let askedKyc = false
	watch(() => page.value.kyc?.status, (status) => {
		if (status !== "Pending" || askedKyc || context.route.query.step !== "kyc") return
		askedKyc = true
		completeKyc()
	}, { immediate: true })

	const sendPledgeOtp = () => run("send_pledge_otp", {}, () => { pledgeSent.value = true })
	const confirmPledge = () => run("confirm_pledge", { otp: pledgeOtp.value }, () => { pledgeSent.value = false; advance() })

	const saveBank = () => run("save_bank_account", { account_number: accountNumber.value, ifsc: ifsc.value }, advance)

	const sendEsignOtp = () => run("send_esign_otp", {}, () => {
		esignSent.value = true
		context.securedLoan.reload()
	})
	const confirmEsign = () => run("confirm_esign", { otp: esignOtp.value }, () => { esignSent.value = false; advance() })

	return { tone, open, logout, showAlerts, alertsTab, sidebarCollapsed, ...search, ...menus, pan, collateral, holdingsRequest, holdingsOtp, notApproved, chosen, loanAmount, tenure, pledgeOtp, pledgeSent, accountNumber, ifsc, esignOtp, esignSent, busy, shown, viewStep, money, verifyPan, sendHoldingsOtp, fetchHoldings, refetch, toggle, sent, chosenEligible, limit, useLimit, canApply, startApplication, startKyc, completeKyc, sendPledgeOtp, confirmPledge, saveBank, sendEsignOtp, confirmEsign }
}
