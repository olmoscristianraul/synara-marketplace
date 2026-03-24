# -*- coding: utf-8 -*-
import logging

from odoo import Command, api, fields, models, _

_logger = logging.getLogger(__name__)


class MarketplaceCommissionRule(models.Model):
    _name = 'marketplace.commission.rule'
    _description = 'Regla de comisión del marketplace'
    _order = 'priority, id'

    name = fields.Char(string='Nombre', required=True)
    commission_percent = fields.Float(string='Comisión (%)', required=True, default=22.0)
    category_id = fields.Many2one(
        'product.category',
        string='Categoría de producto',
        help='Si se define, aplica solo a productos de esta categoría.',
    )
    seller_id = fields.Many2one(
        'res.partner',
        string='Vendedor específico',
        domain="[('is_marketplace_seller', '=', True)]",
        help='Si se define, aplica solo a este vendedor.',
    )
    priority = fields.Integer(
        string='Prioridad',
        default=10,
        help='Menor número = mayor prioridad. Las reglas específicas deben tener menor prioridad.',
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company.id,
    )

    @api.constrains('commission_percent')
    def _check_commission_percent(self):
        for rule in self:
            if rule.commission_percent < 0 or rule.commission_percent > 100:
                raise models.ValidationError(_(
                    'La comisión debe estar entre 0%% y 100%%.'
                ))

    @api.model
    def get_commission_for(self, seller, product_template=None):
        """Resolve the applicable commission % for a seller/product pair.

        Resolution order (first match wins):
        1. Rule with both seller + category
        2. Rule with seller only
        3. Rule with category only
        4. Seller's own override (seller_commission_percent on partner)
        5. Global default from settings
        """
        domain_base = [('active', '=', True)]
        category = product_template.categ_id if product_template else False

        # 1. Seller + category
        if seller and category:
            rule = self.search(
                domain_base + [
                    ('seller_id', '=', seller.id),
                    ('category_id', '=', category.id),
                ],
                limit=1,
            )
            if rule:
                return rule.commission_percent

        # 2. Seller only
        if seller:
            rule = self.search(
                domain_base + [
                    ('seller_id', '=', seller.id),
                    ('category_id', '=', False),
                ],
                limit=1,
            )
            if rule:
                return rule.commission_percent

        # 3. Category only
        if category:
            rule = self.search(
                domain_base + [
                    ('seller_id', '=', False),
                    ('category_id', '=', category.id),
                ],
                limit=1,
            )
            if rule:
                return rule.commission_percent

        # 4. Seller override
        if seller and seller.seller_commission_percent:
            return seller.seller_commission_percent

        # 5. Global default
        IrConfig = self.env['ir.config_parameter'].sudo()
        default = IrConfig.get_param('synara_mp.default_commission', '22.0')
        try:
            return float(default)
        except (TypeError, ValueError):
            return 22.0


class MarketplaceCommissionLine(models.Model):
    _name = 'marketplace.commission.line'
    _description = 'Línea de comisión del marketplace'
    _inherit = ['mail.thread']
    _order = 'create_date desc, id desc'

    seller_id = fields.Many2one(
        'res.partner',
        string='Vendedor',
        required=True,
        domain="[('is_marketplace_seller', '=', True)]",
        index=True,
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Pedido de venta',
        required=True,
        index=True,
    )
    sale_order_name = fields.Char(
        string='Nº pedido',
        related='sale_order_id.name',
        store=True,
    )
    sale_date = fields.Datetime(
        string='Fecha de venta',
        default=fields.Datetime.now,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Moneda',
        required=True,
        default=lambda self: self.env.company.currency_id.id,
    )
    sale_amount = fields.Monetary(
        string='Venta bruta',
        currency_field='currency_id',
        required=True,
    )
    commission_percent = fields.Float(
        string='Comisión (%)',
        required=True,
    )
    commission_amount = fields.Monetary(
        string='Monto comisión',
        currency_field='currency_id',
        compute='_compute_commission_amount',
        store=True,
    )
    seller_amount = fields.Monetary(
        string='Monto vendedor',
        currency_field='currency_id',
        compute='_compute_commission_amount',
        store=True,
    )
    state = fields.Selection([
        ('pending', 'Pendiente'),
        ('invoiced', 'Facturada'),
    ], string='Estado', default='pending', tracking=True, index=True)
    invoice_id = fields.Many2one(
        'account.move',
        string='Factura',
        copy=False,
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company.id,
    )

    @api.depends('sale_amount', 'commission_percent')
    def _compute_commission_amount(self):
        for line in self:
            commission = (line.sale_amount or 0.0) * (line.commission_percent or 0.0) / 100.0
            line.commission_amount = commission
            line.seller_amount = (line.sale_amount or 0.0) - commission

    # ── Monthly Invoice Generation ──
    @api.model
    def _cron_generate_monthly_commission_invoices(self):
        """Generates one invoice per seller for all pending commission lines."""
        pending_lines = self.search([('state', '=', 'pending')])
        if not pending_lines:
            return

        # Group by seller
        sellers = {}
        for line in pending_lines:
            sellers.setdefault(line.seller_id.id, self.env['marketplace.commission.line'])
            sellers[line.seller_id.id] |= line

        AccountMove = self.env['account.move'].with_context(default_move_type='out_invoice')

        for seller_id, lines in sellers.items():
            seller = self.env['res.partner'].browse(seller_id)
            journal = self._get_commission_journal(seller)
            if not journal:
                _logger.warning(
                    'No se pudo generar factura de comisiones para el vendedor %s: falta diario de venta.',
                    seller.display_name,
                )
                continue

            invoice_lines = []
            for line in lines:
                invoice_lines.append(Command.create({
                    'name': _('Comisión marketplace - Pedido %s') % line.sale_order_name,
                    'quantity': 1.0,
                    'price_unit': line.commission_amount,
                }))

            if not invoice_lines:
                continue

            invoice_vals = {
                'move_type': 'out_invoice',
                'partner_id': seller.id,
                'company_id': lines[0].company_id.id,
                'currency_id': lines[0].currency_id.id,
                'journal_id': journal.id,
                'invoice_date': fields.Date.context_today(self),
                'invoice_origin': _('Comisiones Marketplace'),
                'ref': _('Comisiones %s') % seller.display_name,
                'invoice_line_ids': invoice_lines,
            }

            invoice = AccountMove.create(invoice_vals)
            lines.write({
                'state': 'invoiced',
                'invoice_id': invoice.id,
            })
            _logger.info(
                'Factura de comisiones %s generada para vendedor %s (%d líneas).',
                invoice.name,
                seller.display_name,
                len(lines),
            )

    def _get_commission_journal(self, seller):
        """Find the appropriate sales journal for commission invoicing."""
        company = seller.company_id or self.env.company
        return self.env['account.journal'].search([
            ('type', '=', 'sale'),
            ('company_id', '=', company.id),
        ], limit=1)
