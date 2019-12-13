# -*- coding: utf-8 -*-
from openerp import _, api, exceptions, fields, models
from openerp.exceptions import UserError, ValidationError


class ValidateAttendanceSheet(models.TransientModel):
    _name = "beesdoo.shift.sheet.validate"
    _description = """Check the user name and validate sheet.
    Useless for users in group_cooperative_admin"""
    _inherit = ["barcodes.barcode_events_mixin"]

    @api.multi
    def _default_annotation(self):
        """
        The annotation is pre-filled with a warning message
        if a regular worker is added and should have been expected.
        """

        sheet_id = self._context.get("active_id")
        sheet_model = self._context.get("active_model")
        sheet = self.env[sheet_model].browse(sheet_id)
        warning_message = ""

        for added_shift in sheet.added_shift_ids:
            is_regular_worker = added_shift.worker_id.working_mode == "regular"
            is_compensation = added_shift.is_compensation

            if is_regular_worker and not is_compensation:
                warning_message += (
                    _(
                        "Warning : %s attended its shift as a normal one but was not expected. "
                        "Something may be wrong in his/her personnal informations.\n\n"
                    )
                    % added_shift.worker_id.name
                )
        return warning_message

    barcode = fields.Char(string="Barcode", required=True)
    annotation = fields.Text(
        "Important information requiring permanent member assistance",
        default=_default_annotation,
    )
    feedback = fields.Text("General feedback")
    worker_nb_feedback = fields.Selection(
        [
            ("not_enough", "Not enough"),
            ("enough", "Enough"),
            ("too_many", "Too many"),
        ],
        string="Number of workers",
        required=True,
    )

    def on_barcode_scanned(self, barcode):
        self.barcode = barcode

    @api.multi
    def validate_sheet(self):
        sheet_id = self._context.get("active_id")
        sheet_model = self._context.get("active_model")
        sheet = self.env[sheet_model].browse(sheet_id)
        card = self.env["member.card"].search([("barcode", "=", self.barcode)])
        if not len(card):
            raise UserError(_("Please set a correct barcode."))
        partner = card[0].partner_id
        is_admin = partner.user_ids.has_group(
            "beesdoo_shift.group_cooperative_admin"
        )
        if not partner.super and not is_admin:
            raise UserError(
                _(
                    "Only super-cooperators and administrators can validate attendance sheets."
                )
            )
        if self.annotation:
            sheet.annotation += self.annotation
        if sheet.feedback:
            sheet.feedback += self.feedback
        sheet.worker_nb_feedback = self.worker_nb_feedback
        sheet.validate(partner or self.env.user.partner_id)