# -*- coding: utf-8 -*-
import logging

from odoo import SUPERUSER_ID, Command, api, fields, models, _
from odoo.exceptions import ValidationError

LOGGER = logging.getLogger(__name__)
FREEMIUM_CODE = 'FREEMIUM'


class SaleSubscription(models.Model):
	_inherit = 'sale.subscription'

	BILLABLE_STATES = ('trial', 'active', 'grace')

	fotoapp_is_photographer_plan = fields.Boolean(
		string='Suscripción FotoApp', default=False, index=True
	)
	plan_id = fields.Many2one(
		'fotoapp.plan', string='Plan FotoApp', tracking=True
	)
	partner_ref = fields.Char(string='N° Partner', related='partner_id.ref', store=True)
	state = fields.Selection(
		[
			('draft', 'Borrador'),
			('trial', 'Periodo de prueba'),
			('active', 'Activa'),
			('grace', 'En gracia'),
			('suspended', 'Suspendida'),
			('expired', 'Expirada'),
			('canceled', 'Cancelada'),
		],
		string='Estado',
		default='draft',
		tracking=True,
	)
	start_date = fields.Date(
		string='Fecha de registro', related='date_start', store=True, readonly=False
	)
	activation_date = fields.Date(string='Fecha de activación')
	trial_end_date = fields.Date(string='Fin de prueba')
	next_billing_date = fields.Date(
		string='Próxima facturación', related='recurring_next_date', store=True, readonly=False
	)
	end_date = fields.Date(string='Fin de vigencia')
	grace_until = fields.Date(string='Gracia hasta')
	cancellation_date = fields.Date(string='Fecha de cancelación')
	autopay_enabled = fields.Boolean(string='Cobros automáticos', default=True)
	mercadopago_preapproval_id = fields.Char(string='Preapproval Mercado Pago')
	mercadopago_status = fields.Char(string='Estado Mercado Pago')
	mercadopago_checkout_url = fields.Char(string='URL renovación MP')
	notes = fields.Text(string='Notas internas')
	plan_photo_limit = fields.Integer(
		string='Límite de fotos', related='plan_id.photo_limit', store=False
	)
	plan_album_limit = fields.Integer(
		string='Límite de álbumes', related='plan_id.album_limit', store=False
	)
	plan_event_limit = fields.Integer(
		string='Límite de eventos', related='plan_id.event_limit', store=False
	)
	plan_storage_limit_gb = fields.Float(
		string='Límite de almacenamiento (GB)', related='plan_id.storage_limit_gb', store=False
	)
	plan_storage_limit_mb = fields.Integer(
		string='Límite de almacenamiento (MB)', related='plan_id.storage_limit_mb', store=False
	)
	usage_photo_count = fields.Integer(compute='_compute_usage_metrics', store=True)
	usage_album_count = fields.Integer(compute='_compute_usage_metrics', store=True)
	usage_event_count = fields.Integer(compute='_compute_usage_metrics', store=True)
	usage_storage_bytes = fields.Float(
		compute='_compute_usage_metrics',
		store=True,
		help='Bytes utilizados por el fotógrafo; float para evitar overflow en planes grandes.',
	)
	usage_storage_mb = fields.Float(
		string='Uso de almacenamiento (MB)', compute='_compute_usage_metrics', store=True
	)
	storage_limit_bytes = fields.Float(
		string='Límite de almacenamiento (bytes)',
		compute='_compute_limit_flags',
		store=True,
		help='Se almacena como float para soportar límites mayores a 2GB.',
	)
	usage_last_update = fields.Datetime(string='Última actualización', readonly=True)
	is_over_photo_limit = fields.Boolean(compute='_compute_limit_flags', store=True)
	is_over_album_limit = fields.Boolean(compute='_compute_limit_flags', store=True)
	is_over_event_limit = fields.Boolean(compute='_compute_limit_flags', store=True)
	is_over_storage_limit = fields.Boolean(compute='_compute_limit_flags', store=True)
	event_ids = fields.One2many('tienda.foto.evento', 'plan_subscription_id', string='Eventos')
	album_ids = fields.One2many('tienda.foto.album', 'plan_subscription_id', string='Álbumes')
	asset_ids = fields.One2many('tienda.foto.asset', 'plan_subscription_id', string='Fotos')
	responsible_user_id = fields.Many2one(
		'res.users', string='Ejecutivo asignado', default=lambda self: self.env.user
	)


	@api.depends('asset_ids', 'asset_ids.file_size_bytes', 'album_ids', 'event_ids')
	def _compute_usage_metrics(self):
		for subscription in self:
			subscription.usage_photo_count = len(subscription.asset_ids)
			subscription.usage_album_count = len(subscription.album_ids)
			subscription.usage_event_count = len(subscription.event_ids)
			bytes_used = float(sum(subscription.asset_ids.mapped('file_size_bytes'))) if subscription.asset_ids else 0.0
			subscription.usage_storage_bytes = bytes_used
			subscription.usage_storage_mb = bytes_used / (1024 ** 2) if bytes_used else 0.0
			subscription.usage_last_update = fields.Datetime.now()

	@api.depends('usage_photo_count', 'usage_album_count', 'usage_event_count', 'usage_storage_bytes')
	def _compute_limit_flags(self):
		for subscription in self:
			plan = subscription.plan_id
			subscription.is_over_photo_limit = bool(plan and plan.photo_limit and subscription.usage_photo_count > plan.photo_limit)
			subscription.is_over_album_limit = bool(plan and plan.album_limit and subscription.usage_album_count > plan.album_limit)
			subscription.is_over_event_limit = bool(plan and plan.event_limit and subscription.usage_event_count > plan.event_limit)
			storage_limit_mb = (plan.storage_limit_mb or int((plan.storage_limit_gb or 0.0) * 1024)) if plan else 0
			storage_limit_bytes = float(storage_limit_mb or 0) * 1024 * 1024
			subscription.storage_limit_bytes = storage_limit_bytes
			subscription.is_over_storage_limit = bool(storage_limit_bytes and subscription.usage_storage_bytes > storage_limit_bytes)

	def action_activate(self):
		for subscription in self.filtered('fotoapp_is_photographer_plan'):
			if subscription.state not in {'draft', 'trial', 'grace'}:
				continue
			subscription.state = 'active'
			today = fields.Date.context_today(subscription)
			subscription.activation_date = today
			if not subscription.next_billing_date:
				subscription.next_billing_date = subscription._compute_next_cycle_date(today)

	def action_enter_grace(self):
		for subscription in self.filtered('fotoapp_is_photographer_plan'):
			subscription.state = 'grace'
			if not subscription.grace_until:
				subscription.grace_until = fields.Date.add(fields.Date.context_today(subscription), days=7)

	def action_suspend(self):
		for subscription in self.filtered('fotoapp_is_photographer_plan'):
			subscription.state = 'suspended'

	def action_cancel(self):
		for subscription in self.filtered('fotoapp_is_photographer_plan'):
			subscription.state = 'canceled'
			subscription.cancellation_date = fields.Date.context_today(subscription)

	def action_mark_expired(self):
		for subscription in self.filtered('fotoapp_is_photographer_plan'):
			subscription.state = 'expired'
			subscription.end_date = fields.Date.context_today(subscription)

	def check_limits(self, metric):
		self.ensure_one()
		plan = self.plan_id
		if not plan:
			return True
		if metric == 'photo' and plan.photo_limit:
			return self.usage_photo_count <= plan.photo_limit
		if metric == 'album' and plan.album_limit:
			return self.usage_album_count <= plan.album_limit
		if metric == 'event' and plan.event_limit:
			return self.usage_event_count <= plan.event_limit
		if metric == 'storage':
			limit_mb = plan.storage_limit_mb or int((plan.storage_limit_gb or 0.0) * 1024)
			limit_bytes = limit_mb * 1024 * 1024 if limit_mb else 0
			if limit_bytes:
				return self.usage_storage_bytes <= limit_bytes
		return True

	@api.constrains('partner_id', 'plan_id', 'state', 'fotoapp_is_photographer_plan')
	def _constrain_unique_active(self):
		active_states = {'trial', 'active', 'grace'}
		flagged = self.filtered(lambda s: s.fotoapp_is_photographer_plan and s.state in active_states)
		for sub in flagged:
			domain = [
				('id', '!=', sub.id),
				('partner_id', '=', sub.partner_id.id),
				('state', 'in', list(active_states)),
				('fotoapp_is_photographer_plan', '=', True),
			]
			if self.search_count(domain):
				raise ValidationError(_('El fotógrafo ya posee una suscripción activa.'))

	def can_store_bytes(self, bytes_to_add):
		self.ensure_one()
		plan = self.plan_id
		if not plan:
			return True
		limit_mb = plan.storage_limit_mb or int((plan.storage_limit_gb or 0.0) * 1024)
		if not limit_mb:
			return True
		limit_bytes = limit_mb * 1024 * 1024
		return (self.usage_storage_bytes + float(bytes_to_add)) <= limit_bytes

	def remaining_storage_bytes(self):
		self.ensure_one()
		plan = self.plan_id
		if not plan:
			return False
		limit_mb = plan.storage_limit_mb or int((plan.storage_limit_gb or 0.0) * 1024)
		if not limit_mb:
			return False
		limit_bytes = limit_mb * 1024 * 1024
		return max(limit_bytes - self.usage_storage_bytes, 0.0)

	def _handle_successful_payment(self):
		for subscription in self.filtered('fotoapp_is_photographer_plan'):
			today = fields.Date.context_today(subscription)
			subscription.write({
				'state': 'active',
				'grace_until': False,
				'activation_date': today,
			})

	def _apply_nonpayment_downgrade(self):
		freemium_plan = self.env['fotoapp.plan'].search([('code', '=', FREEMIUM_CODE)], limit=1)
		for subscription in self.filtered('fotoapp_is_photographer_plan'):
			values = {
				'state': 'active',
				'next_billing_date': False,
			}
			if freemium_plan and subscription.plan_id != freemium_plan:
				values['plan_id'] = freemium_plan.id
			subscription.write(values)

	def _eligible_for_billing(self):
		return self.filtered(
			lambda s: s.fotoapp_is_photographer_plan
			and s.state in self.BILLABLE_STATES
			and s.plan_id
			and not s.plan_id.is_freemium_plan()
		)

	def _compute_next_cycle_date(self, billing_date):
		self.ensure_one()
		if not billing_date:
			return False
		plan = self.plan_id
		if plan:
			return billing_date + plan._get_billing_relativedelta()
		return fields.Date.add(billing_date, days=30)

	@api.model
	def _get_default_currency(self):
		currency = self.env.ref('base.ARS', raise_if_not_found=False)
		if not currency:
			currency = self.env['res.currency'].search([('name', '=', 'ARS')], limit=1)
		if currency and not currency.active:
			currency.sudo().write({'active': True})
		return currency

	def _generate_subscription_debt(self, billing_date=None, force=False):
		Debt = self.env['fotoapp.debt'].sudo()
		today = fields.Date.context_today(self)
		default_currency = self._get_default_currency()
		created_debts = self.env['fotoapp.debt']
		for subscription in self._eligible_for_billing():
			current_billing = billing_date or subscription.next_billing_date or today
			if not current_billing:
				continue
			existing = Debt.search([
				('subscription_id', '=', subscription.id),
				('debt_type', '=', 'subscription'),
				('billing_date', '=', current_billing),
			], limit=1)
			if existing and not force:
				subscription.sudo().write({'next_billing_date': subscription._compute_next_cycle_date(current_billing)})
				continue
			amount = subscription.plan_id.monthly_fee
			if not amount:
				subscription.sudo().write({'next_billing_date': subscription._compute_next_cycle_date(current_billing)})
				continue
			currency = default_currency or subscription.plan_id.currency_id or self.env.company.currency_id
			debt_vals = {
				'partner_id': subscription.partner_id.id,
				'subscription_id': subscription.id,
				'plan_id': subscription.plan_id.id,
				'debt_type': 'subscription',
				'amount': amount,
				'currency_id': currency.id,
				'billing_date': current_billing,
				'due_date': current_billing,
				'grace_end_date': fields.Date.add(current_billing, days=15),
			}
			debt = Debt.create(debt_vals)
			created_debts |= debt
			subscription.sudo().write({'next_billing_date': subscription._compute_next_cycle_date(current_billing)})
		if created_debts:
			created_debts._create_internal_invoices()

	@api.model
	def fotoapp_cron_generate_subscription_debts(self):
		today = fields.Date.context_today(self)
		domain = [
			('fotoapp_is_photographer_plan', '=', True),
			('state', 'in', list(self.BILLABLE_STATES)),
			('plan_id.is_freemium', '=', False),
			('plan_id.code', '!=', FREEMIUM_CODE),
			('next_billing_date', '!=', False),
			('next_billing_date', '<=', today),
		]
		subscriptions = self.sudo().search(domain)
		subscriptions._generate_subscription_debt()

	@api.model
	def fotoapp_cron_handle_overdue_debts(self):
		today = fields.Date.context_today(self)
		Debt = self.env['fotoapp.debt'].sudo()
		pending = Debt.search([
			('debt_type', '=', 'subscription'),
			('state', '=', 'pending'),
			('due_date', '<', today),
		])
		pending.mark_in_grace()

		expired = Debt.search([
			('debt_type', '=', 'subscription'),
			('state', 'in', ['pending', 'in_grace']),
			('grace_end_date', '<', today),
		])
		expired.mark_expired()

	def write(self, vals):
		manual_next_billing = 'next_billing_date' in vals and vals['next_billing_date']
		manual_activation = 'activation_date' in vals and vals['activation_date']
		res = super().write(vals)
		flagged = self.filtered('fotoapp_is_photographer_plan')
		if flagged and not self.env.context.get('fotoapp_skip_manual_billing'):
			today = fields.Date.context_today(self)
			if manual_activation and not manual_next_billing:
				for sub in flagged.filtered(lambda s: s.activation_date and not s.next_billing_date):
					next_cycle = sub._compute_next_cycle_date(sub.activation_date)
					sub.with_context(fotoapp_skip_manual_billing=True).sudo().write({'next_billing_date': next_cycle})
			if manual_next_billing:
				billable = flagged.filtered(lambda s: s.next_billing_date and s.next_billing_date <= today)
				if billable:
					billable.with_context(fotoapp_skip_manual_billing=True)._generate_subscription_debt(force=True)
		return res

	def fotoapp_is_freemium(self):
		self.ensure_one()
		plan = self.plan_id
		if not plan:
			return False
		return plan.is_freemium or plan.code == FREEMIUM_CODE

	def _fotoapp_ensure_subscription_lines(self):
		for subscription in self.filtered('fotoapp_is_photographer_plan'):
			if subscription.sale_subscription_line_ids:
				continue
			plan = subscription.plan_id
			if not plan:
				continue
			line_commands = plan._prepare_subscription_line_commands()
			if not line_commands:
				continue
			subscription.write({'sale_subscription_line_ids': line_commands})

	def fotoapp_should_skip_oca_cron(self):
		self.ensure_one()
		return self.fotoapp_is_photographer_plan

	@api.model
	def cron_subscription_management(self):
		non_fotoapp = self.search([('fotoapp_is_photographer_plan', '!=', True)])
		if not non_fotoapp:
			return None
		return super(SaleSubscription, non_fotoapp).cron_subscription_management()

	@api.model
	def fotoapp_create_subscription(self, partner, plan, notes=None):
		template = plan._get_subscription_template() if plan else False
		if not template:
			raise ValidationError(_('Configurá una plantilla de suscripción para el plan %(plan)s.', plan=plan.name if plan else 'N/A'))
		Pricelist = self.env['product.pricelist'].sudo().with_context(active_test=False)
		pricelist = partner.with_context(active_test=False).property_product_pricelist
		if not pricelist:
			pricelist = Pricelist.search([], limit=1)
		if not pricelist:
			pricelist = Pricelist.search([('name', 'ilike', 'Public')], limit=1)
		if not pricelist:
			pricelist = self._fotoapp_get_default_pricelist()
		if not pricelist:
			raise ValidationError(_('No se encontró una lista de precios para la suscripción. Creá o configura una lista de precios por defecto.'))
		if not pricelist.active:
			pricelist.write({'active': True})
		today = fields.Date.context_today(self)
		line_commands = plan._prepare_subscription_line_commands() if plan else []
		next_cycle = today + plan._get_billing_relativedelta() if plan else fields.Date.add(today, days=30)
		values = {
			'partner_id': partner.id,
			'template_id': template.id,
			'pricelist_id': pricelist.id,
			'company_id': partner.company_id.id or self.env.company.id,
			'plan_id': plan.id,
			'fotoapp_is_photographer_plan': True,
			'state': 'draft',
			'date_start': today,
			'activation_date': today,
			'recurring_next_date': next_cycle,
			'notes': notes,
			'responsible_user_id': self.env.user.id,
		}
		if plan and plan.journal_id:
			values['journal_id'] = plan.journal_id.id
		if line_commands:
			values['sale_subscription_line_ids'] = line_commands
		subscription = self.create(values)
		subscription.action_activate()
		return subscription


	def _fotoapp_migrate_legacy_plan_subscriptions(self):
		if not self._fotoapp_has_legacy_data():
			return
		config = self.env['ir.config_parameter'].sudo()
		if config.get_param('fotoapp.legacy_subscriptions_migrated'):
			return
		rows = self._fotoapp_fetch_legacy_rows()
		if not rows:
			config.set_param('fotoapp.legacy_subscriptions_migrated', '1')
			return
		default_template = self._fotoapp_get_default_template()
		default_pricelist = self._fotoapp_get_default_pricelist()
		if not default_template or not default_pricelist:
			LOGGER.warning('FotoApp: se omitió la migración de suscripciones porque falta plantilla o lista de precios por defecto.')
			return
		partner_map = self._fotoapp_get_partner_map(rows)
		plan_map = self._fotoapp_get_plan_map(rows)
		default_company = self._fotoapp_get_reference_company()
		default_user = self.env.user or self.env['res.users'].browse(SUPERUSER_ID)
		today = fields.Date.context_today(self)
		Subscription = self.with_context(
			mail_create_nolog=True,
			tracking_disable=True,
			fotoapp_skip_manual_billing=True,
		).sudo()
		valid_states = {'draft', 'trial', 'active', 'grace', 'suspended', 'expired', 'canceled'}
		mapping = {}
		skipped = set()
		for row in rows:
			legacy_id = row['id']
			partner = partner_map.get(row.get('partner_id'))
			plan = plan_map.get(row.get('plan_id'))
			if not partner or not plan:
				skipped.add(legacy_id)
				continue
			template = plan.subscription_template_id or default_template
			pricelist = partner.property_product_pricelist or default_pricelist
			company = partner.company_id or default_company
			if not template or not pricelist or not company:
				skipped.add(legacy_id)
				continue
			code = row.get('name') or f"FAPP-{legacy_id:05d}"
			state = row.get('state') if row.get('state') in valid_states else 'active'
			date_start = row.get('start_date') or row.get('activation_date') or today
			activation_date = row.get('activation_date') or date_start
			next_billing = row.get('next_billing_date')
			if not next_billing:
				next_billing = activation_date + plan._get_billing_relativedelta()
			autopay = True if row.get('autopay_enabled') is None else bool(row.get('autopay_enabled'))
			user_id = row.get('responsible_user_id') or default_user.id or SUPERUSER_ID
			line_commands = plan._prepare_subscription_line_commands()
			vals = {
				'partner_id': partner.id,
				'company_id': company.id,
				'template_id': template.id,
				'pricelist_id': pricelist.id,
				'user_id': user_id,
				'code': code,
				'fotoapp_is_photographer_plan': True,
				'plan_id': plan.id,
				'state': state,
				'date_start': date_start,
				'activation_date': activation_date,
				'recurring_next_date': next_billing,
				'trial_end_date': row.get('trial_end_date'),
				'date': row.get('end_date'),
				'grace_until': row.get('grace_until'),
				'cancellation_date': row.get('cancellation_date'),
				'notes': row.get('notes'),
				'autopay_enabled': autopay,
				'responsible_user_id': row.get('responsible_user_id') or default_user.id,
				'mercadopago_preapproval_id': row.get('mercadopago_preapproval_id'),
				'mercadopago_status': row.get('mercadopago_status'),
				'mercadopago_checkout_url': row.get('mercadopago_checkout_url'),
			}
			if plan.journal_id:
				vals['journal_id'] = plan.journal_id.id
			if line_commands:
				vals['sale_subscription_line_ids'] = line_commands
			try:
				subscription = Subscription.create(vals)
			except Exception as exc:
				LOGGER.exception('FotoApp: error migrando la suscripción %s: %s', legacy_id, exc)
				skipped.add(legacy_id)
				continue
			mapping[legacy_id] = subscription.id
		if mapping:
			self._fotoapp_update_fk_columns(mapping)
		if skipped:
			self._fotoapp_clear_fk_columns(skipped)
		if mapping or skipped:
			config.set_param('fotoapp.legacy_subscriptions_migrated', '1')
			LOGGER.info('FotoApp: migradas %s suscripciones (omitidas %s).', len(mapping), len(skipped))

	def _fotoapp_cleanup_orphan_references(self):
		tables = (
			('res_partner', 'active_plan_subscription_id'),
			('fotoapp_debt', 'subscription_id'),
			('tienda_foto_evento', 'plan_subscription_id'),
			('tienda_foto_album', 'plan_subscription_id'),
			('tienda_foto_asset', 'plan_subscription_id'),
		)
		for table, column in tables:
			query = f"""
				UPDATE {table} target
				SET {column} = NULL
				WHERE {column} IS NOT NULL
				AND NOT EXISTS (
					SELECT 1 FROM sale_subscription s WHERE s.id = target.{column}
				)
			"""
			self.env.cr.execute(query)
		self.env.cr.execute("""
			UPDATE res_partner rp
			SET plan_id = NULL
			WHERE plan_id IS NOT NULL
			AND (
				rp.active_plan_subscription_id IS NULL OR NOT EXISTS (
					SELECT 1 FROM sale_subscription s
					WHERE s.id = rp.active_plan_subscription_id AND s.plan_id = rp.plan_id
				)
			)
		""")

	def _fotoapp_has_legacy_data(self):
		self.env.cr.execute("SELECT to_regclass('public.fotoapp_plan_subscription')")
		table_name = self.env.cr.fetchone()[0]
		if not table_name:
			return False
		self.env.cr.execute('SELECT 1 FROM fotoapp_plan_subscription LIMIT 1')
		return bool(self.env.cr.fetchone())

	def _fotoapp_fetch_legacy_rows(self):
		self.env.cr.execute("""
			SELECT legacy.id, legacy.partner_id, legacy.plan_id, legacy.name,
				legacy.state, legacy.start_date, legacy.activation_date,
				legacy.trial_end_date, legacy.next_billing_date, legacy.end_date,
				legacy.grace_until, legacy.cancellation_date, legacy.notes,
				legacy.autopay_enabled, legacy.responsible_user_id, legacy.company_id,
				legacy.usage_photo_count, legacy.usage_album_count, legacy.usage_event_count,
				legacy.usage_storage_bytes, legacy.usage_storage_mb, legacy.usage_last_update,
				legacy.create_uid, legacy.create_date, legacy.write_uid, legacy.write_date,
				legacy.mercadopago_preapproval_id, legacy.mercadopago_status, legacy.mercadopago_checkout_url,
				partner.company_id AS partner_company_id,
				plan.subscription_template_id AS plan_template_id
			FROM fotoapp_plan_subscription legacy
			LEFT JOIN res_partner partner ON partner.id = legacy.partner_id
			LEFT JOIN fotoapp_plan plan ON plan.id = legacy.plan_id
			ORDER BY legacy.id
		""")
		columns = [col[0] for col in self.env.cr.description]
		return [dict(zip(columns, row)) for row in self.env.cr.fetchall()]

	def _fotoapp_get_partner_map(self, rows):
		partner_ids = {row.get('partner_id') for row in rows if row.get('partner_id')}
		if not partner_ids:
			return {}
		partners = self.env['res.partner'].sudo().browse(list(partner_ids)).exists()
		return {partner.id: partner for partner in partners}

	def _fotoapp_get_plan_map(self, rows):
		plan_ids = {row.get('plan_id') for row in rows if row.get('plan_id')}
		if not plan_ids:
			return {}
		plans = self.env['fotoapp.plan'].sudo().browse(list(plan_ids)).exists()
		return {plan.id: plan for plan in plans}

	def _fotoapp_get_reference_company(self):
		company = self.env.company
		if not company or not company.exists():
			company = self.env['res.company'].sudo().search([], limit=1)
		return company

	def _fotoapp_get_default_pricelist(self):
		Pricelist = self.env['product.pricelist'].sudo().with_context(active_test=False)
		pricelist = Pricelist.search([], limit=1)
		if pricelist:
			if not pricelist.active:
				pricelist.write({'active': True})
			return pricelist
		company = self._fotoapp_get_reference_company()
		currency = company.currency_id or self.env['res.currency'].sudo().search([], limit=1)
		return Pricelist.create({
			'name': 'FotoApp Default Pricelist',
			'currency_id': currency.id,
		})

	def _fotoapp_get_default_template(self):
		template = self.env.ref('fotoapp.fotoapp_subscription_template', raise_if_not_found=False)
		if not template:
			template = self.env['sale.subscription.template'].sudo().search([], limit=1)
		return template

	def _fotoapp_update_fk_columns(self, mapping):
		if not mapping:
			return
		pairs = list(mapping.items())
		updates = (
			('res_partner', 'active_plan_subscription_id'),
			('fotoapp_debt', 'subscription_id'),
			('tienda_foto_evento', 'plan_subscription_id'),
			('tienda_foto_album', 'plan_subscription_id'),
			('tienda_foto_asset', 'plan_subscription_id'),
		)
		for table, column in updates:
			query = f'UPDATE {table} SET {column} = %s WHERE {column} = %s'
			self.env.cr.executemany(query, [(new_id, old_id) for (old_id, new_id) in pairs])
		self.env.cr.execute("""
			UPDATE res_partner rp
			SET plan_id = sub.plan_id
			FROM sale_subscription sub
			WHERE rp.active_plan_subscription_id = sub.id
		""")

	def _fotoapp_clear_fk_columns(self, legacy_ids):
		if not legacy_ids:
			return
		ids = list(legacy_ids)
		updates = (
			('res_partner', 'active_plan_subscription_id'),
			('fotoapp_debt', 'subscription_id'),
			('tienda_foto_evento', 'plan_subscription_id'),
			('tienda_foto_album', 'plan_subscription_id'),
			('tienda_foto_asset', 'plan_subscription_id'),
		)
		for table, column in updates:
			query = f'UPDATE {table} SET {column} = NULL WHERE {column} = ANY(%s)'
			self.env.cr.execute(query, (ids,))
		self.env.cr.execute('UPDATE res_partner SET plan_id = NULL WHERE active_plan_subscription_id IS NULL')
