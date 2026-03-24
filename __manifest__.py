# -*- coding: utf-8 -*-
{
    'name': 'Synara Marketplace',
    'summary': 'Multi-seller marketplace with MercadoPago split payments',
    'description': """
        Convierte el eCommerce de Odoo en un marketplace multi-vendedor.
        Cada vendedor conecta su cuenta de MercadoPago y recibe pagos directos.
        La plataforma cobra una comisión configurable por cada venta.
    """,
    'author': 'HC Sinergia',
    'website': 'https://hcsinergia.com',
    'category': 'Sales',
    'version': '18.0.1.0.0',

    'depends': [
        'base',
        'product',
        'account',
        'website',
        'website_sale',
        'portal',
        'mail',
        'payment_mercado_pago',
    ],

    'data': [
        # 1. Security
        'security/marketplace_security.xml',
        'security/ir.model.access.csv',
        # 2. Views
        'views/marketplace_seller_views.xml',
        'views/marketplace_commission_views.xml',
        'views/res_config_settings_views.xml',
        'views/marketplace_menus.xml',
        'views/seller_portal_templates.xml',
        'views/seller_product_templates.xml',
        'views/seller_order_templates.xml',
        'views/seller_commission_templates.xml',
        # 3. Data
        'data/marketplace_data.xml',
    ],

    'license': 'AGPL-3',
    'installable': True,
    'application': True,
    'auto_install': False,
}
