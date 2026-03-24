# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class FotoappPhotographerStatement(models.Model):
    _name = 'fotoapp.photographer.statement'
    _description = 'Liquidaciones de fotógrafos'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'period_end desc, id desc'

    name = fields.Char(string='Referencia', required=True, copy=False, default=lambda self: _('Liquidación borrador'))
    partner_id = fields.Many2one('res.partner', string='Fotógrafo', required=True, domain="[('is_photographer', '=', True)]")
    period_start = fields.Date(string='Periodo desde', required=True)
    period_end = fields.Date(string='Periodo hasta', required=True)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('pending', 'Pendiente de pago'),
        ('paid', 'Pagada'),
        ('cancelled', 'Cancelada'),
    ], string='Estado', default='draft', tracking=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id.id, required=True)
    commission_percent = fields.Float(string='Comisión aplicada (%)', default=0.0)
    sale_total = fields.Monetary(string='Ventas brutas')
    commission_total = fields.Monetary(string='Total comisión')
    adjustment_total = fields.Monetary(string='Ajustes', help='Montos manuales positivos o negativos.')
    payout_total = fields.Monetary(string='Pago neto', compute='_compute_totals', store=True)
    payout_date = fields.Date(string='Fecha de pago')
    payment_reference = fields.Char(string='Referencia bancaria')
    line_ids = fields.One2many('fotoapp.photographer.statement.line', 'statement_id', string='Detalle')
    sale_count = fields.Integer(string='Cantidad de ventas', compute='_compute_totals', store=True)

    @api.depends('sale_total', 'commission_total', 'adjustment_total', 'line_ids.net_amount')
    def _compute_totals(self):
        for statement in self:
            sale_total = sum(statement.line_ids.mapped('sale_amount'))
            commission_total = sum(statement.line_ids.mapped('commission_amount'))
            net_total = sum(statement.line_ids.mapped('net_amount'))
            statement.sale_total = sale_total
            statement.commission_total = commission_total
            statement.sale_count = len(statement.line_ids)
            statement.payout_total = net_total + (statement.adjustment_total or 0.0)

    def action_confirm(self):
        self.write({'state': 'pending'})

    def action_register_payment(self):
        for statement in self:
            statement.state = 'paid'
            statement.payout_date = fields.Date.context_today(statement)

    def action_cancel(self):
        self.write({'state': 'cancelled'})


class FotoappPhotographerStatementLine(models.Model):
    _name = 'fotoapp.photographer.statement.line'
    _description = 'Detalle de liquidación de fotógrafo'
    _order = 'sale_date desc, id desc'

    statement_id = fields.Many2one('fotoapp.photographer.statement', required=True, ondelete='cascade')
    asset_id = fields.Many2one('tienda.foto.asset', string='Foto vendida', required=True)
    album_id = fields.Many2one('tienda.foto.album', string='Álbum relacionado')
    sale_order_line_id = fields.Many2one('sale.order.line', string='Línea de venta')
    customer_id = fields.Many2one('res.partner', string='Cliente final')
    sale_date = fields.Datetime(string='Fecha de venta')
    sale_amount = fields.Monetary(string='Venta bruta', currency_field='currency_id', required=True)
    commission_percent = fields.Float(string='Comisión aplicada (%)', default=0.0)
    commission_amount = fields.Monetary(string='Monto comisión', currency_field='currency_id', compute='_compute_net_amount', store=True)
    net_amount = fields.Monetary(string='Pago neto', currency_field='currency_id', compute='_compute_net_amount', store=True)
    currency_id = fields.Many2one('res.currency', related='statement_id.currency_id', store=True, readonly=True)

    @api.depends('sale_amount', 'commission_percent')
    def _compute_net_amount(self):
        for line in self:
            commission = (line.sale_amount or 0.0) * (line.commission_percent or 0.0) / 100.0
            line.commission_amount = commission
            line.net_amount = (line.sale_amount or 0.0) - commission
