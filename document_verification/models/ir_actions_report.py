import base64
import io
import logging

import lxml.html
import qrcode

from odoo import models

_logger = logging.getLogger(__name__)


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    def _generate_qrcode_base64(self, url):
        """Generate a QR code PNG as base64 string."""
        buf = io.BytesIO()
        qrcode.make(url, box_size=4, border=2).save(buf, optimise=True, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()

    def _render_qweb_pdf_prepare_streams(self, report_ref, data, res_ids=None):
        """Pass res_ids via context so _prepare_html can use them for QR."""
        self = self.with_context(_qr_res_ids=res_ids or [])
        return super()._render_qweb_pdf_prepare_streams(report_ref, data, res_ids=res_ids)

    def _prepare_html(self, html, report_model=False):
        """Inject QR codes into report articles before PDF generation."""
        qr_res_ids = self.env.context.get("_qr_res_ids", [])

        root = lxml.html.fromstring(html, parser=lxml.html.HTMLParser(encoding="utf-8"))
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")

        match_klass = "//div[contains(concat(' ', normalize-space(@class), ' '), ' {} ')]"
        articles = root.xpath(match_klass.format("article"))

        for idx, article in enumerate(articles):
            res_model = article.get("data-oe-model")
            res_id = article.get("data-oe-id")

            # Fallback to report_model + res_ids from context
            if not res_model and report_model:
                res_model = report_model
            if not res_id and idx < len(qr_res_ids):
                res_id = str(qr_res_ids[idx])

            if not res_model or not res_id:
                continue

            url = f"{base_url}/odoo/{res_model}/{res_id}"
            qr_b64 = self._generate_qrcode_base64(url)

            # Insert QR band as first child — pushes all content below
            qr_band = lxml.html.fromstring(
                f'<div style="text-align:right;margin-bottom:4px;">'
                f'<img src="data:image/png;base64,{qr_b64}" '
                f'style="width:80px;height:80px;" alt="QR"/>'
                f'</div>'
            )
            article.insert(0, qr_band)

        modified_html = lxml.html.tostring(root, encoding="unicode")
        return super()._prepare_html(modified_html, report_model=report_model)
