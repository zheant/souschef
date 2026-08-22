import { useEffect, useState } from "react";
import { api, messageOf } from "../api";
import { describeChanges } from "../changes";
import type { Household, Plan, PriceCoverage, PriceRefresh, SolverConfigInput, Store } from "../types";
import ResultScreen from "./Result";
import { WeekSummary } from "../components/WeekSummary";

/** Écran 1 — Planification : orchestrateur entre la génération, la
 *  confirmation post-génération et le résultat. État initial : seulement
 *  le bouton Générer. Une fois un plan optimal obtenu, une liste de
 *  confirmation s'intercale (pilote, docs/product-pilot.md — remplace le
 *  garde-manger à quantité suivie) : tous les ingrédients requis par le
 *  menu, essentiels pré-décochés (supposés déjà présents), le reste
 *  pré-coché (à acheter de toute façon). L'usager corrige ce qui manque
 *  réellement, puis ``finalize_plan`` verrouille le menu et détermine la
 *  logistique d'achat finale. Une fois confirmé, l'écran affiche le
 *  résultat (ses propres sous-onglets « Cette semaine »/« Épicerie »,
 *  `Result.tsx`, inchangé). */
/** Aujourd'hui en ISO local — `toISOString()` passe par UTC et décale d'un
 *  jour en soirée au Québec (UTC−4/−5). */
function isoToday(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
const TODAY = isoToday();

/** Date et heure locales d'un horodatage ISO UTC, en clair. */
function dateTimeOf(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("fr-CA", {
    day: "numeric", month: "long", hour: "2-digit", minute: "2-digit",
  });
}

/** Ancienneté en clair — « il y a 3 jours » se lit mieux qu'une date quand la
 *  question est « est-ce que mes prix sont vieux ». */
function ageOf(iso: string): string | null {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const hours = Math.floor((Date.now() - d.getTime()) / 3_600_000);
  if (hours < 1) return "à l'instant";
  if (hours < 24) return `il y a ${hours} h`;
  const days = Math.floor(hours / 24);
  return days === 1 ? "il y a 1 jour" : `il y a ${days} jours`;
}

/** Heure locale d'un horodatage ISO UTC — le serveur écrit en UTC, l'usager
 *  lit l'heure de sa cuisine. */
function timeOf(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleTimeString("fr-CA", { hour: "2-digit", minute: "2-digit" });
}

export default function PlanningScreen(props: {
  config: SolverConfigInput;
  plan: Plan | null;
  household: Household;
  stores: Store[];
  onPlan: (p: Plan) => void;
  onCommitted: (planId: number) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [infeasible, setInfeasible] = useState<Plan | null>(null);
  // Date du plan. Le solveur n'accepte que les prix dont la fenêtre de
  // validité la contient : hors couverture, aucune recette ne survit au
  // préfiltrage. Le défaut vise aujourd'hui, et retombe sur la dernière date
  // couverte quand les circulaires chargées sont plus anciennes — sinon le
  // seul recours était de découvrir la borne par un échec.
  const [coverage, setCoverage] = useState<PriceCoverage | null>(null);
  const [onDate, setOnDate] = useState<string>(TODAY);
  // Génération et Résultat étaient deux onglets séparés — fusionnés ici,
  // il faut un moyen de revenir au formulaire même quand un plan existe
  // déjà (sinon Planification reste coincée sur le dernier résultat).
  const [forceForm, setForceForm] = useState(false);

  // Confirmation post-génération : plan généré mais pas encore finalisé,
  // en attente de correction de la liste d'ingrédients à acheter.
  const [pendingPlan, setPendingPlan] = useState<Plan | null>(null);
  const [toBuy, setToBuy] = useState<Record<string, boolean>>({});
  const [finalizing, setFinalizing] = useState(false);
  const [finalizeError, setFinalizeError] = useState<string | null>(null);
  const [finalizeMsg, setFinalizeMsg] = useState<string | null>(null);

  // Rafraîchissement des prix. La collecte tourne dans un processus détaché
  // (une passe Super C dure une trentaine de minutes, cadencée à une requête
  // toutes les 10 s) : l'écran suit son état, il ne l'attend pas.
  const [refresh, setRefresh] = useState<PriceRefresh | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const loadCoverage = () =>
    api.priceCoverage()
      .then((c) => {
        setCoverage(c);
        if (c.latest && TODAY > c.latest) setOnDate(c.latest);
        else if (c.earliest && TODAY < c.earliest) setOnDate(c.earliest);
      })
      .catch(() => setCoverage(null)); // information d'appoint : son absence
                                       // ne doit pas bloquer la génération.

  useEffect(() => { loadCoverage(); }, []);

  // Une collecte déjà lancée doit se retrouver au rechargement de la page :
  // son état vit côté serveur, pas dans celui de cet écran.
  useEffect(() => {
    api.priceRefresh().then(setRefresh).catch(() => setRefresh(null));
  }, []);

  // Sondage seulement pendant la collecte, et à un rythme qui a un sens pour
  // une tâche de trente minutes. `finished` déclenche une relecture de la
  // couverture : c'est le seul moment où elle a pu changer.
  const refreshing = refresh?.state === "running";
  useEffect(() => {
    if (!refreshing) return;
    const timer = window.setInterval(() => {
      api.priceRefresh()
        .then((r) => {
          setRefresh(r);
          if (r.state !== "running") loadCoverage();
        })
        .catch(() => {});
    }, 5000);
    return () => window.clearInterval(timer);
  }, [refreshing]);

  async function startRefresh() {
    setRefreshError(null);
    try {
      setRefresh(await api.startPriceRefresh("superc"));
    } catch (e) {
      setRefreshError(messageOf(e));
    }
  }

  // Le verdict d'une mise à jour est une nouvelle, pas un statut : « échoué »
  // reste sinon affiché des jours après, et se lit comme une affirmation sur
  // l'état actuel de la base. C'est à qui l'a lu de le faire taire.
  async function dismissRefresh() {
    setRefreshError(null);
    try {
      setRefresh(await api.dismissPriceRefresh());
    } catch (e) {
      setRefreshError(messageOf(e));
    }
  }

  // « constraint » exige U_min : le mode se choisit dans un onglet, la valeur
  // se saisit dans un autre champ, et rien n'empêchait de générer entre les
  // deux. Le serveur refusait alors la configuration — correctement, mais
  // l'écran affichait le refus au lieu de l'éviter.
  const missingUMin =
    props.config.appetence_mode === "constraint" &&
    (props.config.appetence_u_min_dollars == null ||
      Number.isNaN(Number(props.config.appetence_u_min_dollars)));

  const outsideCoverage = Boolean(
    coverage?.earliest && coverage.latest &&
    (onDate < coverage.earliest || onDate > coverage.latest),
  );

  const enabled = Object.entries(props.config)
    .filter(([k, v]) => k.startsWith("enable_") && v)
    .map(([k]) => k.replace("enable_", ""));

  async function generate() {
    setBusy(true); setError(null); setInfeasible(null); setFinalizeMsg(null);
    try {
      const plan = await api.createPlan(props.config, onDate);
      if (plan.solver_status !== "Optimal") { setInfeasible(plan); return; }
      setPendingPlan(plan);
      setToBuy(Object.fromEntries(
        plan.needed_ingredients.map((l) => [l.canonical_ingredient_id, !l.is_staple])
      ));
      setForceForm(false);
    } catch (e) { setError(messageOf(e)); } finally { setBusy(false); }
  }

  async function confirm() {
    if (!pendingPlan) return;
    setFinalizing(true); setFinalizeError(null);
    try {
      const confirmedAvailableIds = pendingPlan.needed_ingredients
        .filter((l) => !toBuy[l.canonical_ingredient_id])
        .map((l) => l.canonical_ingredient_id);
      const r = await api.finalizePlan(pendingPlan.id, props.config, confirmedAvailableIds);
      if (r.changes) setFinalizeMsg(describeChanges(r.changes));
      props.onPlan(r.plan);
      setPendingPlan(null);
    } catch (e) { setFinalizeError(messageOf(e)); } finally { setFinalizing(false); }
  }

  if (pendingPlan) {
    return (
      <section>
        <h2>Confirmer les ingrédients <span className="sub">— corrigez ce que vous avez déjà</span></h2>
        <div className="card">
          <p className="muted" style={{ margin: "0 0 14px" }}>
            Les essentiels sont pré-décochés (supposés déjà présents) ; le
            reste est pré-coché (à acheter de toute façon). Corrigez ce qui
            manque réellement, puis confirmez pour verrouiller le menu et
            obtenir la liste d'épicerie finale.
          </p>
          <div className="table-scroll">
            <table className="ledger">
              <thead><tr><th>À acheter</th><th>Ingrédient</th></tr></thead>
              <tbody>
                {pendingPlan.needed_ingredients.map((l) => (
                  <tr key={l.canonical_ingredient_id}>
                    <td>
                      <input
                        type="checkbox"
                        checked={Boolean(toBuy[l.canonical_ingredient_id])}
                        onChange={() => setToBuy((prev) => ({
                          ...prev, [l.canonical_ingredient_id]: !prev[l.canonical_ingredient_id],
                        }))}
                      />
                    </td>
                    <td>
                      {l.name}
                      {l.is_staple && <span className="badge" style={{ marginLeft: 6 }}>Essentiel</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row" style={{ marginTop: 14 }}>
            <button className="action" onClick={confirm} disabled={finalizing}>
              {finalizing ? <><span className="spin" aria-hidden />Confirmation…</> : "Confirmer"}
            </button>
            {finalizeError && <span className="callout error">{finalizeError}</span>}
          </div>
        </div>
      </section>
    );
  }

  if (props.plan && !forceForm) {
    return (
      <>
        <div className="row" style={{ margin: "18px 0 -8px" }}>
          <button className="action ghost" onClick={() => setForceForm(true)}>
            ‹ Générer un nouveau plan
          </button>
        </div>
        {finalizeMsg && <p className="callout" style={{ margin: "10px 0" }}>{finalizeMsg}</p>}
        <WeekSummary plan={props.plan} />
        <ResultScreen
          plan={props.plan} household={props.household} stores={props.stores}
          config={props.config} onCommitted={props.onCommitted}
        />
      </>
    );
  }

  return (
    <section>
      <h2>Planification <span className="sub">— une résolution, un plan persisté</span></h2>
      <div className="card">
        <p>
          Mécanismes actifs :{" "}
          {enabled.length
            ? enabled.map((f) => <span key={f} className="badge" style={{ marginRight: 6 }}>{f}</span>)
            : <span className="muted">aucun — configuration de développement (un magasin ; appétence selon le profil)</span>}
        </p>
        <p className="muted">Les drapeaux se règlent dans l'onglet Paramètres (mode développeur).</p>
        <div className="row" style={{ gap: 10, alignItems: "baseline", margin: "0 0 14px" }}>
          <label htmlFor="on-date">Semaine du plan</label>
          <input
            id="on-date" type="date" value={onDate}
            min={coverage?.earliest ?? undefined}
            max={coverage?.latest ?? undefined}
            onChange={(e) => setOnDate(e.target.value)}
          />
          {coverage?.earliest && coverage.latest && (
            <span className="muted">
              prix chargés du {coverage.earliest} au {coverage.latest}
              {onDate !== TODAY && " — aujourd'hui n'est pas couvert"}
            </span>
          )}
        </div>
        {outsideCoverage && (
          <p className="callout" role="status" style={{ margin: "0 0 14px" }}>
            Aucun prix chargé ne couvre le {onDate} : la génération échouera.
            Choisir une date entre {coverage?.earliest} et {coverage?.latest},
            ou rafraîchir les prix ci-dessous.
          </p>
        )}
        <div style={{ margin: "0 0 14px" }}>
          {/* Toujours visible, même sans lancement depuis l'application : la
              date vient des dossiers de capture, donc une collecte faite en
              ligne de commande compte aussi. */}
          <p className="muted" style={{ margin: "0 0 8px" }}>
            {refresh?.last_capture_at
              ? <>
                  Dernière collecte Super C :{" "}
                  <strong>{dateTimeOf(refresh.last_capture_at)}</strong>
                  {ageOf(refresh.last_capture_at) && ` — ${ageOf(refresh.last_capture_at)}`}
                </>
              : "Aucune collecte Super C trouvée sur ce poste."}
          </p>
          <button
            className="action ghost"
            onClick={startRefresh}
            disabled={refreshing}
          >
            {refreshing
              ? <><span className="spin" aria-hidden />Mise à jour Super C en cours…</>
              : "Mettre à jour les prix Super C"}
          </button>
          {/* Le chiffre n'est pas décoratif : sans lui, un bouton qui ne rend
              rien pendant une demi-heure passe pour cassé. */}
          <p className="muted" style={{ margin: "6px 0 0" }}>
            Deux temps : collecte des rayons, puis import en base. Une passe
            complète prend une trentaine de minutes — le collecteur s'espace de
            dix secondes par requête, volontairement. Une collecte tronquée
            n'empêche pas l'import de ce qui a été obtenu. Le travail continue
            même si vous quittez cet écran ; Maxi n'est pas incluse, son
            collecteur exigeant une fenêtre de navigateur visible.
          </p>
          {refreshError && (
            <p className="callout error" role="alert" style={{ marginTop: 10 }}>
              {refreshError}
            </p>
          )}
          {refresh && refresh.state !== "idle" && (
            <div className="callout" role="status" style={{ marginTop: 10 }}>
              {refresh.state !== "running" && (
                <button
                  className="dismiss"
                  onClick={dismissRefresh}
                  style={{ float: "right" }}
                  aria-label="Masquer le verdict de la dernière mise à jour"
                >
                  Masquer
                </button>
              )}
              <strong>
                {refresh.state === "running" && "Collecte en cours"}
                {refresh.state === "succeeded" && (
                  refresh.collection_complete === false
                    ? "Prix mis à jour — capture partielle"
                    : "Prix mis à jour"
                )}
                {refresh.state === "failed" && "Dernière tentative : échec"}
              </strong>
              {refresh.started_at && (
                <span className="muted"> — démarrée à {timeOf(refresh.started_at)}</span>
              )}
              {refresh.state === "failed" && refresh.exit_code != null && (
                <span className="muted"> (code {refresh.exit_code})</span>
              )}
              {/* Le chiffre vient du rapport d'import, pas d'une estimation :
                  c'est ce que la base a réellement reçu. */}
              {refresh.state === "succeeded" && refresh.imported && (
                <p style={{ margin: "6px 0 0" }}>
                  {refresh.imported.products_upserted ?? 0} produits,{" "}
                  {refresh.imported.prices_upserted ?? 0} prix écrits en base.
                </p>
              )}
              {refresh.state === "succeeded" && refresh.collection_complete === false && (
                <p className="muted" style={{ margin: "6px 0 0" }}>
                  Super C a paginé moins de produits qu'il n'en annonçait sur
                  certains rayons. Les prix importés sont réels, mais le
                  catalogue de la semaine est incomplet — relancer plus tard
                  peut le compléter.
                </p>
              )}
              {refresh.log_tail.length > 0 && (
                <pre
                  className="mono"
                  style={{
                    marginTop: 8, maxHeight: 160, overflow: "auto",
                    whiteSpace: "pre-wrap", fontSize: "0.8em",
                  }}
                >
                  {refresh.log_tail.join("\n")}
                </pre>
              )}
            </div>
          )}
        </div>
        {missingUMin && (
          <p className="callout" role="status" style={{ margin: "0 0 14px" }}>
            Le mode d'appétence « constraint » a besoin d'un plancher : saisir
            <strong> U_min ($)</strong> dans l'onglet Paramètres, ou revenir au
            mode « objective ».
          </p>
        )}
        <button className="action" onClick={generate} disabled={busy || missingUMin}>
          {busy ? <><span className="spin" aria-hidden />Résolution en cours…</> : "Générer le plan de la semaine"}
        </button>
        {error && <p className="callout error" role="alert">{error}</p>}
        {infeasible && (
          <div className="callout error" role="alert" style={{ marginTop: 14 }}>
            <strong>Infaisable ({infeasible.solver_status}).</strong>{" "}
            {infeasible.diagnostic.infeasibility_note}
            <div className="muted" style={{ marginTop: 6 }}>
              Assertions passées : {infeasible.diagnostic.assertions_passed.join(", ") || "—"}.
              Dernier drapeau activé : <span className="mono">{infeasible.diagnostic.last_enabled_flag ?? "aucun"}</span>.
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
