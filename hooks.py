from odoo import SUPERUSER_ID, api

def post_init_hook(env):
    # Ya no hace falta crear 'env' manualmente, Odoo 18 lo entrega directo.
    
    # 1. Asegurar productos del plan
    env['fotoapp.plan'].sudo().search([])._ensure_plan_products()
    
    # 2. Migraciones de suscripciones
    SaleSubscription = env['sale.subscription']
    SaleSubscription._fotoapp_migrate_legacy_plan_subscriptions()
    SaleSubscription._fotoapp_cleanup_orphan_references()
    
    # 3. Asegurar líneas de suscripción
    SaleSubscription.search([('fotoapp_is_photographer_plan', '=', True)])._fotoapp_ensure_subscription_lines()