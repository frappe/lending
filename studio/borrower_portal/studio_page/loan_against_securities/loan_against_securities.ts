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
	const units = ref({} as Record<string, string>)
	const loanAmount = ref("")
	const tenure = ref("12")
	const pledgeOtp = ref("")
	const pledgeSent = ref(false)
	const accountNumber = ref("")
	const confirmAccount = ref("")
	const ifsc = ref("")
	const esignOtp = ref("")
	const esignSent = ref(false)
	const withdrawAmount = ref("")

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
	// One line per purchase lot, so a fund's units are the sum of its lines.
	watch(() => page.value.application?.lines, (lines) => {
		if (!lines?.length) return
		const saved: Record<string, number> = {}
		lines.forEach((line: any) => { saved[line.holding] = (saved[line.holding] || 0) + line.units })
		chosen.value = Object.keys(saved)
		units.value = Object.fromEntries(Object.entries(saved).map(([holding, count]) => [holding, String(count)]))
	}, { immediate: true })
	const toggle = (holding: any) => {
		if (sent.value || !holding.pledgeable_units) return
		if (chosen.value.includes(holding.holding)) {
			chosen.value = chosen.value.filter((name) => name !== holding.holding)
			return
		}
		chosen.value = [...chosen.value, holding.holding]
		units.value = { ...units.value, [holding.holding]: String(holding.pledgeable_units) }
	}
	const setUnits = (holding: string, value: any) => { units.value = { ...units.value, [holding]: String(value ?? "") } }
	const unitsOf = (row: any) => Number(units.value[row.holding] || 0)
	const unitsValid = (row: any) => unitsOf(row) > 0 && unitsOf(row) <= row.pledgeable_units
	// The same sum the server makes: units × NAV, less the fund's haircut.
	const lends = (row: any) => (unitsValid(row) ? unitsOf(row) * row.nav * (1 - row.haircut / 100) : 0)
	const sent = computed(() => Boolean(page.value.application?.sent))
	const chosenRows = computed(() => holdings.value.filter((row) => chosen.value.includes(row.holding)))
	const chosenEligible = computed(() => chosenRows.value.reduce((sum, row) => sum + lends(row), 0))
	const limit = computed(() => {
		const ceiling = page.value.product?.maximum || 0
		return Math.floor(ceiling ? Math.min(chosenEligible.value, ceiling) : chosenEligible.value)
	})
	const useLimit = () => { loanAmount.value = String(limit.value) }
	watch(() => page.value.application?.amount, (amount) => { if (amount) loanAmount.value = String(amount) }, { immediate: true })
	watch(() => page.value.application?.tenure, (months) => { if (months) tenure.value = String(months) }, { immediate: true })
	const canApply = computed(() =>
		chosenRows.value.length > 0 && chosenRows.value.every(unitsValid)
		&& Number(loanAmount.value) > 0 && Number(loanAmount.value) <= limit.value)
	const startApplication = () =>
		run("start_application", {
			collateral: collateral.value,
			lines: JSON.stringify(chosenRows.value.map((row) => ({ holding: row.holding, units: unitsOf(row) }))),
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

	watch(() => page.value.loan?.available, (available) => { if (available) withdrawAmount.value = String(Math.floor(available)) }, { immediate: true })
	const withdraw = () => run("withdraw", { amount: withdrawAmount.value }, advance)

	return { tone, open, logout, showAlerts, alertsTab, sidebarCollapsed, ...search, ...menus, pan, collateral, holdingsRequest, holdingsOtp, notApproved, chosen, units, loanAmount, tenure, pledgeOtp, pledgeSent, accountNumber, confirmAccount, ifsc, esignOtp, esignSent, withdrawAmount, busy, shown, viewStep, money, verifyPan, sendHoldingsOtp, fetchHoldings, refetch, toggle, setUnits, unitsValid, lends, sent, chosenEligible, limit, useLimit, canApply, startApplication, startKyc, completeKyc, sendPledgeOtp, confirmPledge, saveBank, sendEsignOtp, confirmEsign, withdraw }
}
