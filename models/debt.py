# -*- coding: utf-8 -*-
import logging

from odoo import Command, api, fields, models, _


LOGGER = logging.getLogger(__name__)


class FotoappDebt(models.Model):
    _name = 'fotoapp.debt'
    _description = 'Deudas del fotógrafo'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'due_date DESC, id DESC'

    name = fields.Char(string='Referencia', required=True, copy=False,
                       default=lambda self: self._default_name())
    partner_id = fields.Many2one('res.partner', string='Fotógrafo', required=True, index=True)
    subscription_id = fields.Many2one('sale.subscription', string='Suscripción', index=True)
    plan_id = fields.Many2one('fotoapp.plan', string='Plan asociado')
    debt_type = fields.Selection([
        ('subscription', 'Renovación de plan'),
        ('commission', 'Comisión'),
        ('other', 'Otro'),
    ], string='Tipo de deuda', default='subscription', required=True, index=True)
    amount = fields.Monetary(string='Importe', required=True)
    currency_id = fields.Many2one('res.currency', string='Moneda', required=True,
                                  default=lambda self: self._default_currency())
    billing_date = fields.Date(string='Periodo facturado', required=True)
    due_date = fields.Date(string='Fecha de vencimiento', required=True)
    grace_end_date = fields.Date(string='Fin de gracia', required=True)
    state = fields.Selection([
        ('pending', 'Pendiente'),
        ('in_grace', 'En periodo de gracia'),
        ('paid', 'Pagada'),
        ('expired', 'Expirada'),
    ], string='Estado', default='pending', tracking=True, index=True)
    sale_order_id = fields.Many2one('sale.order', string='Pedido de pago', copy=False)
    sale_order_line_id = fields.Many2one('sale.order.line', string='Línea asociada', copy=False)
    invoice_id = fields.Many2one('account.move', string='Factura', copy=False, readonly=True)
    invoice_state = fields.Selection(related='invoice_id.payment_state', string='Estado factura', store=False, readonly=True)
    payment_ids = fields.Many2many(
        'account.payment',
        'fotoapp_debt_payment_rel',
        'debt_id',
        'payment_id',
        string='Pagos registrados',
        copy=False,
        readonly=True,
    )
    paid_date = fields.Datetime(string='Fecha de pago', copy=False)
    company_id = fields.Many2one('res.company', string='Compañía', required=True,
                                 default=lambda self: self.env.company.id)
    notes = fields.Text(string='Notas internas')

    _sql_constraints = [
        ('fotoapp_debt_unique_cycle',
         'unique(subscription_id, debt_type, billing_date)',
         'Ya existe una deuda generada para este ciclo.'),
    ]

    def _default_name(self):
        return self.env['ir.sequence'].next_by_code('fotoapp.debt') or _('Deuda')

    def _default_currency(self):
        ars = self.env.ref('base.ARS', raise_if_not_found=False)
        if not ars:
            ars = self.env['res.currency'].search([('name', '=', 'ARS')], limit=1)
        if ars and not ars.active:
            ars.sudo().write({'active': True})
        return ars.id if ars else self.env.company.currency_id.id

    def mark_paid(self, paid_date=None):
        for debt in self.filtered(lambda d: d.state != 'paid'):
            date_done = paid_date or fields.Datetime.now()
            debt.write({
                'state': 'paid',
                'paid_date': date_done,
            })
            subscription = debt.subscription_id
            if subscription:
                subscription._handle_successful_payment()

    def mark_in_grace(self):
        self.filtered(lambda d: d.state == 'pending').write({'state': 'in_grace'})

    def mark_expired(self):
        for debt in self.filtered(lambda d: d.state in ('pending', 'in_grace')):
            debt.state = 'expired'
            subscription = debt.subscription_id
            if subscription:
                subscription._apply_nonpayment_downgrade()

    def can_be_paid(self):
        self.ensure_one()
        return self.state in ('pending', 'in_grace')

    def get_portal_label(self):
        self.ensure_one()
        if self.debt_type == 'subscription':
            return _('Renovación de plan')
        if self.debt_type == 'commission':
            return _('Comisión pendiente')
        return _('Deuda')

    def _get_invoice_product(self):
        self.ensure_one()
        plan = self.plan_id
        if plan:
            plan.sudo()._ensure_plan_products()
            product = plan.product_variant_id or (plan.product_template_id.product_variant_id if plan.product_template_id else False)
            if product:
                return product
        template = self.env.ref('fotoapp.product_plan_renewal_template', raise_if_not_found=False)
        if template and template.product_variant_id:
            return template.product_variant_id
        return False

    def _get_invoice_journal(self):
        self.ensure_one()
        if self.plan_id and self.plan_id.journal_id:
            return self.plan_id.journal_id
        return self.env['account.journal'].search([
            ('type', '=', 'sale'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)

    def _prepare_invoice_line_vals(self, product, account):
        self.ensure_one()
        description = '%s - %s' % (self.get_portal_label(), self.billing_date or self.due_date or fields.Date.context_today(self))
        line_vals = {
            'name': description,
            'product_id': product.id,
            'product_uom_id': product.uom_id.id if product.uom_id else False,
            'account_id': account.id if account else False,
            'quantity': 1.0,
            'price_unit': self.amount,
        }
        plan = self.plan_id
        tax_ids = plan._get_plan_tax_ids() if plan else []
        if tax_ids:
            line_vals['tax_ids'] = [Command.set(tax_ids)]
        return line_vals

    def _get_income_account(self, product):
        self.ensure_one()
        plan_account = self.plan_id.income_account_id if self.plan_id else False
        if plan_account:
            return plan_account
        if product.property_account_income_id:
            return product.property_account_income_id
        categ_account = product.categ_id.property_account_income_categ_id if product.categ_id else False
        if categ_account:
            return categ_account
        company = self.company_id
        fallback = getattr(company, 'account_sale_income_account_id', False)
        return fallback

    def _create_internal_invoices(self):
        AccountMove = self.env['account.move'].with_context(default_move_type='out_invoice')
        created = self.env['account.move']
        for debt in self.filtered(lambda d: not d.invoice_id and d.plan_id and d.amount):
            product = debt._get_invoice_product()
            journal = debt._get_invoice_journal()
            if not product or not journal:
                LOGGER.warning('No se pudo crear factura para la deuda %s: faltan producto (%s) o diario (%s).', debt.id, bool(product), bool(journal))
                continue
            account = debt._get_income_account(product)
            if not account:
                LOGGER.warning('No se pudo determinar la cuenta contable para la deuda %s.', debt.id)
                continue
            line_vals = debt._prepare_invoice_line_vals(product, account)
            document_type = debt._get_default_document_type(journal)
            invoice_vals = {
                'move_type': 'out_invoice',
                'partner_id': debt.partner_id.id,
                'company_id': debt.company_id.id,
                'currency_id': debt.currency_id.id,
                'journal_id': journal.id,
                'invoice_date': debt.billing_date or fields.Date.context_today(debt),
                'invoice_date_due': debt.due_date or debt.billing_date,
                'invoice_origin': debt.name,
                'ref': debt.name,
                'payment_reference': debt.name,
                'invoice_line_ids': [Command.create(line_vals)],
            }
            if document_type:
                invoice_vals['l10n_latam_document_type_id'] = document_type.id
            invoice = AccountMove.create(invoice_vals)
            invoice.action_post()
            debt.write({'invoice_id': invoice.id})
            debt.message_post(body=_('Factura %s generada automáticamente.') % (invoice.display_name,))
            created |= invoice
        return created

    def _get_default_document_type(self, journal):
        """Pick a valid LATAM document type when the journal requires it."""
        if not getattr(journal, 'l10n_latam_use_documents', False):
            return False

        DocType = self.env['l10n_latam.document.type']
        country_id = journal.company_id.country_id.id if journal.company_id else False

        journal_docs = getattr(journal, 'l10n_latam_document_type_ids', DocType)
        candidates = journal_docs if journal_docs else DocType

        domain = [('internal_type', '=', 'invoice')]
        if country_id:
            domain.append(('country_id', '=', country_id))

        doc_type = candidates.search(domain, limit=1)
        return doc_type

    @api.model
    def fotoapp_cron_invoice_pending_debts(self, limit=100):
        domain = [
            ('state', 'in', ('pending', 'in_grace')),
            ('invoice_id', '=', False),
            ('plan_id', '!=', False),
        ]
        debts = self.search(domain, limit=limit)
        if debts:
            debts._create_internal_invoices()

    def _fotoapp_register_gateway_payment(self, transaction=None):
        for debt in self:
            invoice = debt.invoice_id
            if not invoice or invoice.payment_state in ('paid', 'in_payment') or not invoice.amount_residual:
                continue
            journal = debt._get_gateway_journal(transaction)
            if not journal:
                LOGGER.warning('No se pudo registrar el pago de Mercado Pago para la deuda %s: falta diario.', debt.id)
                continue
            ctx = {
                'active_model': 'account.move',
                'active_ids': invoice.ids,
            }
            wizard_vals = {
                'journal_id': journal.id,
                'amount': invoice.amount_residual,
                'payment_date': fields.Date.context_today(debt),
                'communication': _('Pago Mercado Pago - %s') % (invoice.payment_reference or debt.name),
            }
            register = self.env['account.payment.register'].with_context(ctx).create(wizard_vals)
            payments = register._create_payments()
            if payments:
                debt.write({'payment_ids': [Command.link(p.id) for p in payments]})

    def _get_gateway_journal(self, transaction=None):
        self.ensure_one()
        if transaction and transaction.provider_id and transaction.provider_id.journal_id:
            return transaction.provider_id.journal_id
        IrConfig = self.env['ir.config_parameter'].sudo()
        journal_id = IrConfig.get_param('fotoapp.mp_gateway_journal_id')
        if journal_id:
            journal = self.env['account.journal'].browse(int(journal_id))
            if journal.exists():
                return journal
        return self.env['account.journal'].search([
            ('type', 'in', ('bank', 'cash')),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
