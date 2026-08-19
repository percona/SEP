/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

/**
 * Where an operator reads what this tool does before enabling it.
 *
 * To be defined: the Support diagnostics page is not published yet, so this
 * points at the documentation entry point. Replacing it is a one-line change.
 */
export const SUPPORT_DIAGNOSTICS_DOCS_URL = 'https://docs.percona.com';

export const PERCONA_SUPPORT_URL = 'https://www.percona.com/services/support';

/** The settings class and key an admin has to supply to enable delivery. */
export const DELIVERY_SETTING_CLASS = 'SEPSettings';
export const DELIVERY_INPUTS_KEY = 'DIAGNOSTICS_DELIVERY_INPUTS';
export const DELIVERY_PLAN_KEY = 'DIAGNOSTICS_DELIVERY';

/**
 * Product copy for the setup screen.
 *
 * `heading`, `title`, `description` and `consentNote` are shared with the
 * PMM-embedded copy of this app (`ServiceNowSetupGate.messages.ts`) and must
 * stay word-for-word identical — only the call to action differs, because SEP
 * has no guided ServiceNow form to send an operator to.
 */
export const Messages = {
  loading: 'Checking the ServiceNow connection…',
  heading: 'Support diagnostics',
  title: 'Send diagnostics straight to your support cases',
  description:
    "This tool runs Percona's diagnostic scripts against your monitored environment and uploads the results directly to a case in Percona's ServiceNow, skipping manual collection.",
  consentNote: 'No data is collected or sent until someone selects a script and confirms.',
  howItWorks: 'How Support diagnostics works',
  subscriptionPrompt: "Don't have a Percona Support subscription?",
  subscriptionLinkText: 'Learn about Percona Support',

  // ── Call to action (SEP-specific) ───────────────────────────────────
  notConfigured:
    "Diagnostics delivery isn't configured on this SEP deployment. Ask an administrator to configure it.",
  adminInstructions:
    `Supply the ${DELIVERY_INPUTS_KEY} key of the ${DELIVERY_SETTING_CLASS} class in Settings. ` +
    `The delivery plan itself (${DELIVERY_PLAN_KEY}) comes from settings.yaml or the environment ` +
    'and is not editable from the UI.',
  openSettings: 'Open settings',
};
