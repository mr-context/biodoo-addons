/** @odoo-module **/

import { Component, useState, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

class OcrProgressTerminal extends Component {
    static template = "hr_dz_ocr.OcrProgressTerminal";
    static props = { ...standardWidgetProps };

    setup() {
        this.busService = useService("bus_service");
        this.actionService = useService("action");
        this.terminalRef = useRef("terminal");

        this.state = useState({
            messages: [],
            done: false,
        });

        this._onNotification = this._onNotification.bind(this);

        onMounted(() => {
            // S'abonner aux notifications bus
            this.busService.subscribe("hr_ocr/progress", this._onNotification);
            // Message initial
            this._addMessage("En attente du serveur OCR...", "info");
        });

        onWillUnmount(() => {
            this.busService.subscribe("hr_ocr/progress", this._onNotification);
        });
    }

    _onNotification(payload) {
        const wizardId = this.props.record && this.props.record.resId;

        // Filtrer par wizard_id si disponible
        if (wizardId && payload.wizard_id && payload.wizard_id !== wizardId) {
            return;
        }

        if (payload.done) {
            this._addMessage("Traitement terminé !", "success");
            this.state.done = true;
            // Recharger le formulaire après un court délai
            setTimeout(() => {
                this.actionService.doAction({
                    type: "ir.actions.act_window",
                    res_model: "hr.ocr.wizard",
                    res_id: wizardId,
                    views: [[false, "form"]],
                    target: "new",
                });
            }, 800);
            return;
        }

        if (payload.message) {
            const type = payload.message.startsWith("ERREUR") ? "error" : "info";
            this._addMessage(payload.message, type);
        }
    }

    _addMessage(text, type = "info") {
        this.state.messages.push({ text, type });
        // Auto-scroll vers le bas
        requestAnimationFrame(() => {
            const el = document.querySelector(".ocr-terminal");
            if (el) {
                el.scrollTop = el.scrollHeight;
            }
        });
    }
}

// Enregistrer comme widget de formulaire
registry.category("view_widgets").add("ocr_progress_terminal", {
    component: OcrProgressTerminal,
});
