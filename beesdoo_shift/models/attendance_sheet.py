# -*- coding: utf-8 -*-

from datetime import date, datetime, timedelta

from lxml import etree

from openerp import _, api, exceptions, fields, models
from openerp.exceptions import UserError, ValidationError


class AttendanceSheetShift(models.AbstractModel):
    _name = "beesdoo.shift.sheet.shift"
    _description = "Copy of an actual shift into an attendance sheet"

    @api.model
    def default_task_type_id(self):
        parameters = self.env["ir.config_parameter"]
        id = (
            int(parameters.get_param("beesdoo_shift.default_task_type_id"))
            or 1
        )
        task_types = self.env["beesdoo.shift.type"]
        return task_types.browse(id)

    # Related actual shift
    task_id = fields.Many2one("beesdoo.shift.shift", string="Task")
    attendance_sheet_id = fields.Many2one(
        "beesdoo.shift.sheet",
        string="Attendance Sheet",
        required=True,
        ondelete="cascade",
    )
    stage = fields.Selection(
        [
            ("present", "Present"),
            ("absent_0", "Absent / 0 Compensation"),
            ("absent_1", "Absent / 1 Compensation"),
            ("absent_2", "Absent / 2 Compensations"),
        ],
        string="Shift Stage",
    )
    worker_id = fields.Many2one(
        "res.partner",
        string="Worker",
        domain=[
            ("eater", "=", "worker_eater"),
            ("working_mode", "in", ("regular", "irregular")),
            ("state", "not in", ("unsubscribed", "resigning")),
        ],
    )
    task_type_id = fields.Many2one(
        "beesdoo.shift.type", string="Task Type", default=default_task_type_id
    )
    super_coop_id = fields.Many2one(
        "res.users",
        string="Super Cooperative",
        domain=[("partner_id.super", "=", True)],
    )
    working_mode = fields.Selection(
        related="worker_id.working_mode", string="Working Mode"
    )
    # The two exclusive booleans are gathered in a simple one
    is_compensation = fields.Boolean(
        string="Compensation shift ?",
        help="Only for regular workers"
    )
    def get_actual_stage(self):
        """
         Mapping function returning the actual id
         of corresponding beesdoo.shift.stage,
         because we prefer users to select number of compensations
         on the sheet rather than the exact stage name.
         """
        if not self.working_mode or not self.stage:
            raise UserError(
                _("Impossible to map task stage, all values are not set.")
            )
        if self.working_mode == "regular":
            if self.stage == "present":
                return "done"
            if self.stage == "absent_0":
                return "excused_necessity"
            if self.stage == "absent_1":
                return "excused"
            if self.stage == "absent_2":
                return "absent"
        if self.working_mode == "irregular":
            if self.stage == "present":
                return "done"
            return "absent"


class AttendanceSheetShiftExpected(models.Model):
    _name = "beesdoo.shift.sheet.expected"
    _description = "Expected Shift"
    _inherit = ["beesdoo.shift.sheet.shift"]

    replacement_worker_id = fields.Many2one(
        "res.partner",
        string="Replacement Worker",
        domain=[
            ("eater", "=", "worker_eater"),
            ("working_mode", "=", "regular"),
            ("state", "not in", ("unsubscribed", "resigning")),
        ],
    )


class AttendanceSheetShiftAdded(models.Model):
    """The added shifts stage must be Present
    (add an SQL constraint ?)
    """

    _name = "beesdoo.shift.sheet.added"
    _description = "Added Shift"
    _inherit = ["beesdoo.shift.sheet.shift"]

    stage = fields.Selection(default="present")

    @api.onchange("working_mode")
    def on_change_working_mode(self):
        self.stage = "present"
        self.is_compensation = self.working_mode == "regular"


class AttendanceSheet(models.Model):
    _name = "beesdoo.shift.sheet"
    _inherit = [
        "mail.thread",
        "ir.needaction_mixin",
        "barcodes.barcode_events_mixin",
    ]
    _description = "Attendance sheet"
    _order = "start_time"

    name = fields.Char(string="Name", compute="_compute_name")
    time_slot = fields.Char(
        string="Time Slot",
        compute="_compute_time_slot",
        store=True,
        readonly=True,
    )
    active = fields.Boolean(string="Active", default=1)
    state = fields.Selection(
        [("not_validated", "Not Validated"), ("validated", "Validated"),],
        string="State",
        readonly=True,
        index=True,
        default="not_validated",
        track_visibility="onchange",
    )
    start_time = fields.Datetime(
        string="Start Time", required=True, readonly=True
    )
    end_time = fields.Datetime(string="End Time", required=True, readonly=True)
    day = fields.Date(string="Day", compute="_compute_day", store=True)
    week = fields.Char(
        string="Week",
        help="Computed from planning names",
        compute="_compute_week",
    )

    expected_shift_ids = fields.One2many(
        "beesdoo.shift.sheet.expected",
        "attendance_sheet_id",
        string="Expected Shifts",
    )
    added_shift_ids = fields.One2many(
        "beesdoo.shift.sheet.added",
        "attendance_sheet_id",
        string="Added Shifts",
    )

    max_worker_no = fields.Integer(
        string="Maximum number of workers",
        default=0,
        readonly=True,
        help="Indicative maximum number of workers.",
    )
    annotation = fields.Text("Annotation", default="")
    is_annotated = fields.Boolean(
        compute="_compute_is_annotated",
        string="Annotation",
        readonly=True,
        store=True,
    )
    is_read = fields.Boolean(
        string="Mark as read",
        help="Has annotation been read by an administrator ?",
        default=False,
        track_visibility="onchange",
    )
    feedback = fields.Text("Feedback")
    worker_nb_feedback = fields.Selection(
        [
            ("not_enough", "Not enough"),
            ("enough", "Enough"),
            ("too_many", "Too many"),
        ],
        string="Number of workers",
    )
    validated_by = fields.Many2one(
        "res.partner",
        string="Validated by",
        domain=[
            ("eater", "=", "worker_eater"),
            ("super", "=", True),
            ("working_mode", "=", "regular"),
            ("state", "not in", ("unsubscribed", "resigning")),
        ],
        track_visibility="onchange",
        readonly=True,
    )

    _sql_constraints = [
        (
            "check_no_annotation_mark_read",
            "CHECK ((is_annotated=FALSE AND is_read=FALSE) OR is_annotated=TRUE)",
            _("Non-annotated sheets can't be marked as read."),
        )
    ]

    @api.depends("start_time", "end_time", "week")
    def _compute_name(self):
        for rec in self:
            start_time_dt = fields.Datetime.from_string(rec.start_time)
            start_time_dt = fields.Datetime.context_timestamp(
                rec, start_time_dt
            )
            name = "[%s] - " % fields.Date.to_string(start_time_dt)
            if rec.week:
                name += rec.week + " - "
            if rec.time_slot:
                name += rec.time_slot
            rec.name = name

    @api.depends("start_time", "end_time")
    def _compute_time_slot(self):
        for rec in self:
            start_time_dt = fields.Datetime.from_string(rec.start_time)
            start_time_dt = fields.Datetime.context_timestamp(
                rec, start_time_dt
            )
            end_time_dt = fields.Datetime.from_string(rec.end_time)
            end_time_dt = fields.Datetime.context_timestamp(rec, end_time_dt)
            rec.time_slot = (
                start_time_dt.strftime("%H:%M")
                + " - "
                + end_time_dt.strftime("%H:%M")
            )

    @api.depends("start_time")
    def _compute_day(self):
        for rec in self:
            rec.day = fields.Date.from_string(rec.start_time)

    @api.depends("expected_shift_ids")
    def _compute_week(self):
        """
        Compute Week Name from Planning Name of first expected shift
        """
        for rec in self:
            if rec.expected_shift_ids:
                rec.week = rec.expected_shift_ids[0].task_id.planning_id.name

    @api.depends("annotation")
    def _compute_is_annotated(self):
        for rec in self:
            rec.is_annotated = bool(rec.annotation.strip())

    @api.constrains("expected_shift_ids", "added_shift_ids")
    def _constrain_unique_worker(self):
        # Warning : map return generator in python3 (for Odoo 12)
        added_ids = map(lambda s: s.worker_id.id, self.added_shift_ids)
        expected_ids = map(lambda s: s.worker_id.id, self.expected_shift_ids)
        replacement_ids = map(
            lambda s: s.replacement_worker_id.id, self.expected_shift_ids
        )
        replacement_ids = filter(bool, replacement_ids)
        ids = added_ids + expected_ids + replacement_ids

        if (len(ids) - len(set(ids))) > 0:
            raise UserError(
                _(
                    "You can't add the same worker more than once to an attendance sheet."
                )
            )

    @api.constrains(
        "expected_shift_ids",
        "added_shift_ids",
        "annotation",
        "feedback",
        "worker_nb_feedback",
    )
    def _lock_after_validation(self):
        if self.state == "validated":
            raise UserError(
                _("The sheet has already been validated and can't be edited.")
            )

    def on_barcode_scanned(self, barcode):
        if self.state == "validated":
            raise UserError(
                _("You cannot modify a validated attendance sheet.")
            )

        worker = self.env["res.partner"].search([("barcode", "=", barcode)])
        if not len(worker):
            raise UserError(_("Worker not found (invalid barcode or status)."))
        if len(worker) > 1:
            raise UserError(
                _("Multiple workers are corresponding this barcode.")
            )

        if worker.state in ("unsubscribed", "resigning"):
            raise UserError(_("Worker is %s.") % worker.state)
        if worker.working_mode not in ("regular", "irregular"):
            raise UserError(
                _("Worker is %s and should be regular or irregular.")
                % worker.working_mode
            )

        for id in self.expected_shift_ids.ids:
            shift = self.env["beesdoo.shift.sheet.expected"].browse(id)
            if (
                shift.worker_id == worker and not shift.replacement_worker_id
            ) or shift.replacement_worker_id == worker:
                shift.stage = "present"
                return
            if shift.worker_id == worker and shift.replacement_worker_id:
                raise UserError(
                    _("%s was expected as replaced.") % worker.name
                )

        is_compensation = (worker.working_mode == "regular")

        added_ids = map(lambda s: s.worker_id.id, self.added_shift_ids)
        if worker.id in added_ids:
            return

        self.added_shift_ids |= self.added_shift_ids.new(
            {
                "task_type_id": self.added_shift_ids.default_task_type_id(),
                "stage": "present",
                "attendance_sheet_id": self._origin.id,
                "worker_id": worker.id,
                "is_compensation": is_compensation,
            }
        )

    @api.model
    def create(self, vals):
        new_sheet = super(AttendanceSheet, self).create(vals)

        # Creation and addition of the expected shifts corresponding
        # to the time range
        tasks = self.env["beesdoo.shift.shift"]
        expected_shift = self.env["beesdoo.shift.sheet.expected"]
        cancelled_stage = self.env.ref("beesdoo_shift.cancel")
        s_time = fields.Datetime.from_string(new_sheet.start_time)
        e_time = fields.Datetime.from_string(new_sheet.end_time)
        delta = timedelta(minutes=1)

        tasks = tasks.search(
            [
                ("start_time", ">", fields.Datetime.to_string(s_time - delta)),
                ("start_time", "<", fields.Datetime.to_string(s_time + delta)),
                ("end_time", ">", fields.Datetime.to_string(e_time - delta)),
                ("end_time", "<", fields.Datetime.to_string(e_time + delta)),
            ]
        )
        for task in tasks:
            if task.working_mode == "irregular":
                stage = "absent_1"
            else:
                stage = "absent_2"
            if task.worker_id and (task.stage_id != cancelled_stage):
                new_expected_shift = expected_shift.create(
                    {
                        "attendance_sheet_id": new_sheet.id,
                        "task_id": task.id,
                        "worker_id": task.worker_id.id,
                        "replacement_worker_id": task.replaced_id.id,
                        "task_type_id": task.task_type_id.id,
                        "stage": stage,
                        "working_mode": task.working_mode,
                        "is_compensation": task.is_compensation,
                    }
                )
        # Maximum number of workers calculation (count empty shifts)
        new_sheet.max_worker_no = len(tasks)
        return new_sheet

    @api.multi
    def button_mark_as_read(self):
        if self.is_read:
            raise UserError(_("The sheet has already been marked as read."))
        self.is_read = True

    # Workaround to display notifications only
    # for unread and not validated sheets, via a check on domain.
    @api.model
    def _needaction_count(self, domain=None):
        if domain == [
            ("is_annotated", "=", True),
            ("is_read", "=", False),
        ] or domain == [("state", "=", "not_validated")]:
            return self.search_count(domain)
        return

    def validate(self, user):
        self.ensure_one()
        if self.state == "validated":
            raise UserError("The sheet has already been validated.")

        shift = self.env["beesdoo.shift.shift"]
        stage = self.env["beesdoo.shift.stage"]

        # Fields validation
        for added_shift in self.added_shift_ids:
            if not added_shift.worker_id:
                raise UserError(
                    _("Worker must be set for shift %s") % added_shift.id
                )
            if not added_shift.stage:
                raise UserError(
                    _("Shift Stage is missing for %s")
                    % added_shift.worker_id.name
                )
            if not added_shift.task_type_id:
                raise UserError(
                    _("Task Type is missing for %s")
                    % added_shift.worker_id.name
                )
            if not added_shift.working_mode:
                raise UserError(
                    _("Working mode is missing for %s")
                    % added_shift.worker_id.name
                )

        for expected_shift in self.expected_shift_ids:
            if not expected_shift.stage:
                raise UserError(
                    _("Shift Stage is missing for %s")
                    % expected_shift.worker_id.name
                )

        # Expected shifts status update
        for expected_shift in self.expected_shift_ids:
            actual_shift = expected_shift.task_id
            actual_stage = self.env.ref(
                "beesdoo_shift.%s" % expected_shift.get_actual_stage()
            )

            if actual_stage:
                actual_shift.stage_id = actual_stage
                actual_shift.replaced_id = expected_shift.replacement_worker_id

                if expected_shift.stage in ["absent_1", "absent_2"]:
                    mail_template = self.env.ref(
                        "beesdoo_shift.email_template_non_attendance", False
                    )
                    mail_template.send_mail(expected_shift.task_id.id, True)

        # Added shifts status update
        for added_shift in self.added_shift_ids:
            actual_stage = self.env.ref(
                "beesdoo_shift.%s" % added_shift.get_actual_stage()
            )
            is_regular_worker = added_shift.worker_id.working_mode == "regular"
            is_compensation = added_shift.is_compensation

            # Edit a non-assigned shift or create one if none
            non_assigned_shifts = shift.search(
                [
                    ("worker_id", "=", False),
                    ("start_time", "=", self.start_time),
                    ("end_time", "=", self.end_time),
                    ("task_type_id", "=", added_shift.task_type_id.id),
                ],
                limit=1,
            )

            if len(non_assigned_shifts):
                actual_shift = non_assigned_shifts[0]
                actual_shift.write(
                    {
                        "stage_id": actual_stage.id,
                        "worker_id": added_shift.worker_id.id,
                        "stage_id": actual_stage.id,
                        "is_regular": not is_compensation and is_regular_worker,
                        "is_compensation": is_compensation
                        and is_regular_worker,
                    }
                )
            else:
                actual_shift = self.env["beesdoo.shift.shift"].create(
                    {
                        "name": _("[Added Shift] %s") % self.start_time,
                        "task_type_id": added_shift.task_type_id.id,
                        "worker_id": added_shift.worker_id.id,
                        "start_time": self.start_time,
                        "end_time": self.end_time,
                        "stage_id": actual_stage.id,
                        "is_regular": not is_compensation and is_regular_worker,
                        "is_compensation": is_compensation
                        and is_regular_worker,
                    }
                )
            added_shift.task_id = actual_shift.id

        self.validated_by = user
        self.state = "validated"
        return

    @api.multi
    def validate_via_wizard(self):
        self.ensure_one()
        if self.env.user.has_group("beesdoo_shift.group_cooperative_admin"):
            self.validate(self.env.user.partner_id)
            return
        return {
            "type": "ir.actions.act_window",
            "res_model": "beesdoo.shift.sheet.validate",
            "view_type": "form",
            "view_mode": "form",
            "target": "new",
        }

    @api.model
    def _generate_attendance_sheet(self):
        """
        Generate sheets with shifts in the time interval
        defined from corresponding CRON time interval.
        """

        time_ranges = set()
        tasks = self.env["beesdoo.shift.shift"]
        sheets = self.env["beesdoo.shift.sheet"]
        current_time = datetime.now()
        generation_interval_setting = int(self.env["ir.config_parameter"].get_param(
            "beesdoo_shift.attendance_sheet_generation_interval"
        ))

        allowed_time_range = timedelta(minutes=generation_interval_setting)

        tasks = tasks.search(
            [
                ("start_time", ">", str(current_time),),
                ("start_time", "<", str(current_time + allowed_time_range),),
            ]
        )

        for task in tasks:
            start_time = task.start_time
            end_time = task.end_time
            sheets = sheets.search(
                [("start_time", "=", start_time), ("end_time", "=", end_time),]
            )

            if not sheets:
                sheet = sheets.create(
                    {"start_time": start_time, "end_time": end_time}
                )

    @api.model
    def _cron_non_validated_sheets(self):
        sheets = self.env["beesdoo.shift.sheet"]
        non_validated_sheets = sheets.search(
            [
                ("day", "=", date.today() - timedelta(days=1)),
                ("state", "=", "not_validated"),
            ]
        )

        if non_validated_sheets:
            mail_template = self.env.ref(
                "beesdoo_shift.email_template_non_validated_sheet", False
            )
            for rec in non_validated_sheets:
                mail_template.send_mail(rec.id, True)