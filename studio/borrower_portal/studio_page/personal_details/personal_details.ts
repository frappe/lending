import { computed, ref, watch } from "vue"
import { call, toast } from "frappe-ui"
import { tone, appRoute, logout as endSession, useSearch } from "@app/utils/portal"

export default function setup(context: any) {
	const { router } = context
	const showAlerts = ref(false)
	const alertsTab = ref("attention")
	const sidebarCollapsed = ref<boolean | null>(null)
	const editing = ref(false)

	const open = (url?: string) => {
		const to = appRoute(url)
		if (to) router.push(to)
	}
	const logout = () => endSession(router)
	const search = useSearch(open)

	const forms = computed(() => context.profile.data?.forms || {})
	const customer = ref("")
	const form = ref<Record<string, string>>({})
	const identity = ref<Record<string, string>>({})
	const saved = ref("")
	const saving = ref(false)

	const pick = (values: Record<string, string>, fields: string[]) =>
		Object.fromEntries(fields.map((field) => [field, values[field] || ""]))

	const fillForm = () => {
		const values = forms.value[customer.value] || {}
		identity.value = pick(values, ['customer_name', 'customer_type', 'tax_id'])
		form.value = pick(values, ['email', 'mobile', 'phone', 'address_line1', 'address_line2', 'city', 'state', 'pincode', 'country'])
		saved.value = JSON.stringify(form.value)
	}
	watch(forms, (all) => {
		if (!(customer.value in all)) customer.value = context.profile.data?.form_customer || ""
		fillForm()
	}, { immediate: true })
	watch(customer, () => { fillForm(); editing.value = false })

	const dirty = computed(() => JSON.stringify(form.value) !== saved.value)
	const edit = () => { editing.value = true }
	const cancel = () => { fillForm(); editing.value = false }

	const save = () => {
		saving.value = true
		call("lending.portal.profile.save_profile", { customer: customer.value, ...form.value })
			.then((result: any) => {
				toast.success(result?.message || "Your details have been updated.")
				editing.value = false
				context.profile.reload()
			})
			.catch((error: any) => toast.error(String(error.messages?.[0] || error)))
			.finally(() => { saving.value = false })
	}

	return { tone, open, logout, showAlerts, alertsTab, sidebarCollapsed, ...search, editing, form, identity, customer, dirty, edit, cancel, save, saving }
}
