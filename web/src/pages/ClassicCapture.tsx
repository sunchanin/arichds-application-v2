import { useEffect, useState } from "react";

import { api, type ClassicCaptureView } from "../api";
import type { CaptureRequest } from "../capture";
import "./classic-capture.css";

/**
 * The toolbar's ten icons — cut from the owner-supplied strip of ARICHDS
 * Meter's own toolbar at their native size (`web/public/images/classic/`),
 * each at the x the reference image shows it (frame x minus the toolbar's
 * own left edge at 5). Bitmaps, not redrawn: they are the one thing the
 * previous program's look cannot be reproduced from measurements alone.
 */
const TOOLBAR_ICONS: { file: string; left: number; top: number }[] = [
  // The strip shows the first button pressed, with its own frame; only its glyph is cut (ref rows 12..41).
  { file: "icon-01.png", left: 10, top: 5 },
  { file: "icon-02.png", left: 59, top: 1 },
  { file: "icon-03.png", left: 109, top: 1 },
  { file: "icon-04.png", left: 163, top: 1 },
  { file: "icon-05.png", left: 210, top: 1 },
  { file: "icon-06.png", left: 265, top: 1 },
  { file: "icon-07.png", left: 309, top: 1 },
  { file: "icon-08.png", left: 359, top: 1 },
  { file: "icon-09.png", left: 411, top: 1 },
  { file: "icon-10.png", left: 462, top: 1 },
];

/** Absolute text placed by its measured position inside its group. */
function Text({ left, top, className, children }: { left: number; top: number; className?: string; children: string }) {
  return (
    <span className={className ? `cc-text ${className}` : "cc-text"} style={{ left, top }}>
      {children}
    </span>
  );
}

/**
 * The Classic capture page (ADR 0028) — a picture of the window of ARICHDS
 * Meter, the program the customer ran before ARICHDS, drawn only to be
 * photographed by the headless renderer at a fixed 1280×709.
 *
 * Reached by no menu and no URL a person would type: `App.tsx` renders it in
 * place of the whole shell when the seeded capture request says
 * `style: "classic"`. Everything it shows comes from one endpoint, already
 * formatted — this component is a layout, not a formatter (spec: one
 * formatting rule, testable in Python, cannot drift between two places).
 *
 * **Every value is true or is inert.** The folder, the site (in the Group box), the device,
 * the statistics and the rows are what the endpoint answered; the Auto Read
 * Schedule panel is fixed text because it claims nothing about a bill.
 *
 * The rows carry `data-row-key` exactly as the Billing page's rows do, so the
 * renderer's row-id gate (`capture/dom.py` — `CLASSIC_TABLE_BODY_ROW_SELECTOR`)
 * waits for the ten periods in the page's order before it photographs.
 * Until the endpoint answers the table is empty and the gate keeps waiting;
 * if it never answers, the capture times out and is logged, and the PDF is
 * untouched — the same failure a Standard capture has.
 */
export function ClassicCapture({ request }: { request: CaptureRequest }) {
  const [view, setView] = useState<ClassicCaptureView | null>(null);

  useEffect(() => {
    api
      .classicCapture(request.deviceId, request.anchorId)
      .then(setView)
      .catch(() => setView(null));
  }, [request.deviceId, request.anchorId]);

  const serial = view?.meter_serial ?? request.meterSerial ?? "";
  const device = view ? `${view.brand} - ${view.meter_serial}` : "";

  return (
    <div className="classic-capture">
      <div className="cc-toolbar">
        <div className="cc-toolbar-checked" />
        {TOOLBAR_ICONS.map((icon) => (
          <img key={icon.file} className="cc-toolbar-icon" style={{ left: icon.left, top: icon.top }} src={`/images/classic/${icon.file}`} alt="" />
        ))}
      </div>

      <div className="cc-group cc-save-path">
        <span className="cc-group-caption">Save Path</span>
        <div className="cc-field">{view?.save_path ?? ""}</div>
        <div className="cc-button">Browse</div>
      </div>

      <div className="cc-group cc-data-billing">
        <span className="cc-group-caption">Data Billing</span>
        <Text left={9} top={13}>
          Group:
        </Text>
        <div className="cc-combo cc-group-combo">{view?.site_name ?? ""}</div>

        <div className="cc-group cc-statistics">
          <span className="cc-group-caption">Statistics Summary</span>
          <Text left={13} top={10}>
            Total Devices:
          </Text>
          <Text left={139} top={10} className="cc-stat-total">
            {view ? String(view.statistics.total) : ""}
          </Text>
          <Text left={211} top={10}>
            Devices with Issues:
          </Text>
          <Text left={368} top={10} className="cc-stat-issues">
            {view ? String(view.statistics.issues) : ""}
          </Text>
          <Text left={444} top={10}>
            Complete Devices:
          </Text>
          <Text left={605} top={10} className="cc-stat-complete">
            {view ? String(view.statistics.complete) : ""}
          </Text>
        </div>

        <div className="cc-tab cc-tab-selected">Billing</div>
        <div className="cc-tab cc-tab-other">Current</div>
        <div className="cc-tab-panel">
          <Text left={7} top={9}>
            Device:
          </Text>
          <div className="cc-combo cc-device-combo">{device}</div>
          <div className="cc-button cc-read-billing">Read Billing</div>
        </div>
      </div>

      <div className="cc-group cc-auto-read">
        <span className="cc-group-caption">Auto Read Schedule (Default for All Devices)</span>
        <Text left={3} top={17}>
          Time:
        </Text>
        <div className="cc-spinner cc-spinner-hour">
          00
          <span className="cc-spin-up" />
          <span className="cc-spin-divider" />
          <span className="cc-spin-down" />
        </div>
        <Text left={76} top={17}>
          :
        </Text>
        <div className="cc-spinner cc-spinner-minute">
          00
          <span className="cc-spin-up" />
          <span className="cc-spin-divider" />
          <span className="cc-spin-down" />
        </div>
        <Text left={130} top={17} className="cc-status-running">
          Status: Running
        </Text>
        <div className="cc-button cc-stop">Stop</div>
      </div>

      <div className="cc-group cc-data-table">
        <span className="cc-group-caption">Data Table</span>
        <div className="cc-button cc-reload">Reload Table</div>
        <div className="cc-grid">
          <div className="cc-grid-viewport">
            <table>
              <colgroup>
                <col className="cc-col-name" />
                <col className="cc-col-time" />
                <col className="cc-col-kwh" />
                <col className="cc-col-kwh" />
                <col className="cc-col-kwh" />
                <col className="cc-col-kwh" />
                <col className="cc-col-kw" />
                <col className="cc-col-kw" />
                <col className="cc-col-cut" />
              </colgroup>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Time</th>
                  <th>Total kWh Total</th>
                  <th>Total kWh Rate A</th>
                  <th>Total kWh Rate B</th>
                  <th>Total kWh Rate C</th>
                  <th>Prev kW Demand Rate A</th>
                  <th>Time of kW Demand A</th>
                  <th>Prev kW Demand Rate B</th>
                </tr>
              </thead>
              <tbody>
                {(view?.rows ?? []).map((row) => (
                  <tr key={row.id} data-row-key={row.id}>
                    <td>{row.name}</td>
                    <td>{row.time}</td>
                    <td>{row.total_kwh_total}</td>
                    <td>{row.total_kwh_rate_a}</td>
                    <td>{row.total_kwh_rate_b}</td>
                    <td>{row.total_kwh_rate_c}</td>
                    <td>{row.prev_kw_demand_rate_a}</td>
                    <td>{row.time_of_kw_demand_a}</td>
                    <td>{row.prev_kw_demand_rate_b}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="cc-vbar" />
          <div className="cc-hbar" />
        </div>
      </div>

      <Text left={23} top={684}>
        {`Capture bill data ${serial}...`}
      </Text>
    </div>
  );
}
