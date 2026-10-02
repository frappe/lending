import { computed, ref, watch } from "vue"
import { call, toast } from "frappe-ui"
import { tone, appRoute, logout as endSession, useSearch, useMenus } from "@app/utils/portal"

export default function setup(context: any) {
	const { router } = context
	const showAlerts = ref(false)
	const alertsTab = ref("attention")
	const sidebarCollapsed = ref<boolean | null>(null)
	const applicant = ref("")
	const loanProduct = ref("")
	const loanAmount = ref("")
	const proposedTenure = ref("")
	const income = ref("")
	const employmentType = ref("")
	const dateOfBirth = ref("")
	const pan = ref("")

	const open = (url?: string) => {
		const to = appRoute(url)
		if (to) router.push(to)
	}
	const logout = () => endSession(router)
	const search = useSearch(open)
	const menus = useMenus(context.route, open, logout)

	const page = computed(() => context.newApplication.data || {})
	const applicants = computed<any[]>(() => page.value.applicants || [])
	const chosen = computed<any>(() => applicants.value.find((row) => row.value === applicant.value) || {})
	const products = computed<any[]>(() => page.value.products?.[chosen.value.applicant_type] || [])
	const isPerson = computed(() => chosen.value.applicant_type === "Individual")
	const busy = ref(false)
	const offer = ref<Record<string, any>>({})
	// A ref rather than chosen.identity, so the locked boxes bind to something they own.
	const identity = ref<Record<string, string>>({})

	watch(applicants, (all) => {
		if (!all.some((row) => row.value === applicant.value)) applicant.value = all[0]?.value || ""
	}, { immediate: true })

	watch(chosen, (row) => {
		const answers = row.answers || {}
		identity.value = { ...(row.identity || {}) }
		income.value = answers.income || ""
		employmentType.value = answers.employment_type || ""
		dateOfBirth.value = answers.date_of_birth || ""
		pan.value = answers.pan || ""
		proposedTenure.value = answers.proposed_tenure || ""
		if (!products.value.some((product) => product.value === loanProduct.value)) loanProduct.value = ""
	}, { immediate: true })

	const chooseProduct = (product: string) => { loanProduct.value = product }
	const needsMobile = computed(() => Boolean(chosen.value.value && !chosen.value.has_mobile))
	const ready = computed(() => Boolean(loanProduct.value && Number(loanAmount.value) > 0 && chosen.value.has_mobile))

	const submit = () => {
		busy.value = true
		call("lending.portal.apply.create_customer_lead", {
			customer: applicant.value,
			loan_product: loanProduct.value,
			loan_amount: loanAmount.value,
			proposed_tenure: proposedTenure.value,
			income: income.value,
			employment_type: employmentType.value,
			date_of_birth: dateOfBirth.value,
			pan: pan.value,
		})
			.then((result: any) => { offer.value = result })
			.catch((error: any) => toast.error(String(error?.messages?.[0] || error?.message || error)))
			.finally(() => { busy.value = false })
	}

	const another = () => {
		offer.value = {}
		loanProduct.value = ""
		loanAmount.value = ""
	}

	return { tone, open, logout, showAlerts, alertsTab, sidebarCollapsed, ...search, ...menus, applicant, loanProduct, loanAmount, proposedTenure, income, employmentType, dateOfBirth, pan, applicants, chosen, identity, products, isPerson, busy, offer, chooseProduct, needsMobile, ready, submit, another }
}
