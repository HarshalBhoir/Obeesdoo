# Copyright 2017 - 2020 BEES coop SCRLfs
#   - Robin Keunen <robin@coopiteasy.be>
#   - Houssine bakkali <houssine@coopiteasy.be>
#   - Rémy Taymans <remy@coopiteasy.be>
#   - Elise Dupont
#   - Thibault François
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
{
    'name': "Beescoop Base Module",

    'summary': """
        Module that customize the base module and contains some python tools
     """,

    'description': """
    """,

    'author': "Beescoop - Cellule IT",
    'website': "https://github.com/beescoop/Obeesdoo",

    'category': 'Sales',
    'version': '12.0.1.0.0',

    'depends': ['point_of_sale', 'purchase', 'portal', 'partner_firstname'],

    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'views/partner.xml',
        'wizard/views/member_card.xml',
        'wizard/views/partner.xml',
        'data/default_contact.xml',
        'report/beescard.xml',
    ],
    'demo': [
        'demo/cooperators.xml',
        'demo/users.xml',
    ]
    'installable': False,
}
