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

import { useMemo, type PropsWithChildren } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import CircularProgress from '@mui/material/CircularProgress';
import Link from '@mui/material/Link';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { Link as RouterLink } from 'react-router';
import { useSettingsList, type SettingClassGroup, type SettingResponse } from '@sep/api';
import { ROUTES } from '@sep/shared';
import {
  DELIVERY_INPUTS_KEY,
  DELIVERY_PLAN_KEY,
  DELIVERY_SETTING_CLASS,
  Messages,
  PERCONA_SUPPORT_URL,
  SUPPORT_DIAGNOSTICS_DOCS_URL,
} from './DeliverySetupGate.messages';

/**
 * What the stored settings say about diagnostics delivery.
 *
 * Mirrors the PMM-embedded copy's `ConnectionStatus` — the same three values
 * derived the same way, so the two surfaces cannot disagree about whether a
 * deployment is configured.
 */
export type DeliveryStatus = 'configured' | 'not-configured' | 'drifted';

interface DeliveryInputs {
  endpoint?: string | null;
  secrets?: Record<string, string>;
}

interface StoredDeliveryInputs {
  endpoint: string;
  secrets: Record<string, string>;
  hasOverride: boolean;
  /** Whether the settings response carries the key at all. */
  isPresent: boolean;
}

/** Locate one setting inside the `SEPSettings` group of a LIST response. */
const findSepSetting = (
  groups: SettingClassGroup[] | undefined,
  key: string,
): SettingResponse | undefined =>
  groups
    ?.find((group) => group.setting_class === DELIVERY_SETTING_CLASS)
    ?.settings.find((setting) => setting.key === key);

const asInputs = (value: unknown): DeliveryInputs => {
  if (!value || typeof value !== 'object') {
    return {};
  }
  const { endpoint, secrets } = value as DeliveryInputs;
  return {
    endpoint: typeof endpoint === 'string' ? endpoint : null,
    secrets:
      secrets && typeof secrets === 'object' && !Array.isArray(secrets)
        ? Object.fromEntries(
            Object.entries(secrets).map(([name, secret]) => [
              name,
              typeof secret === 'string' ? secret : '',
            ]),
          )
        : {},
  };
};

/**
 * The secret names this deployment must supply, read from the baked plan.
 *
 * The plan is the declaration SEP validates a write against, so it always wins.
 * The stored inputs are a fallback for a SEP build that does not list the plan
 * at all: their names are only stale if that build also renamed one.
 */
export const declaredSecretNames = (groups: SettingClassGroup[] | undefined): string[] => {
  const planNames = Object.keys(
    asInputs(findSepSetting(groups, DELIVERY_PLAN_KEY)?.value).secrets ?? {},
  );
  if (planNames.length > 0) {
    return planNames;
  }
  return Object.keys(asInputs(findSepSetting(groups, DELIVERY_INPUTS_KEY)?.value).secrets ?? {});
};

/**
 * The stored per-deployment inputs. Secrets come back masked once something is
 * stored, so the values here are only ever compared against the empty string —
 * never inspected for content.
 */
export const storedDeliveryInputs = (
  groups: SettingClassGroup[] | undefined,
): StoredDeliveryInputs => {
  const setting = findSepSetting(groups, DELIVERY_INPUTS_KEY);
  const { endpoint, secrets } = asInputs(setting?.value);
  return {
    endpoint: endpoint ?? '',
    secrets: secrets ?? {},
    hasOverride: setting?.has_override ?? false,
    isPresent: setting !== undefined,
  };
};

/**
 * What the stored inputs say about delivery, without asking SEP a second time.
 *
 * An empty secret is a valid save that leaves delivery unavailable, so it reads
 * as "not configured" rather than as a failure. A declared name with no stored
 * counterpart means the image renamed one after the values were supplied — the
 * value SEP still holds no longer satisfies the plan.
 *
 * A plan that declares no secrets is judged on the override alone: there is no
 * credential left for the deployment to supply, so a stored override is as
 * configured as it can get.
 */
export const deliveryStatus = (
  declaredNames: string[],
  stored: StoredDeliveryInputs,
): DeliveryStatus => {
  if (!stored.hasOverride) {
    return 'not-configured';
  }
  if (declaredNames.length === 0) {
    return 'configured';
  }
  if (declaredNames.some((name) => stored.secrets[name] === undefined)) {
    return 'drifted';
  }
  return declaredNames.every((name) => stored.secrets[name] !== '')
    ? 'configured'
    : 'not-configured';
};

/**
 * What SEP currently holds for diagnostics delivery, read once and derived.
 *
 * The settings LIST is admin-gated (it answers 403 to everyone else), so the
 * `error` this returns is a routine outcome for a regular user rather than an
 * exception — see {@link DeliverySetupGate} for how it is handled.
 */
export const useDeliveryConfiguration = () => {
  const { data: groups, isLoading, error } = useSettingsList();

  const declaredNames = useMemo(() => declaredSecretNames(groups), [groups]);
  const stored = useMemo(() => storedDeliveryInputs(groups), [groups]);

  return {
    declaredNames,
    stored,
    status: deliveryStatus(declaredNames, stored),
    isLoading,
    error,
  };
};

/**
 * What an operator sees instead of the app while delivery is unconfigured:
 * what the tool does, who can enable it, and what it will not do unasked.
 */
const SetupPrompt = ({ isAdmin }: { isAdmin: boolean }) => (
  <Stack gap={3} sx={{ flex: 1 }}>
    <Typography variant="h4">{Messages.heading}</Typography>
    <Stack
      alignItems="center"
      justifyContent="center"
      sx={{ flex: 1, minHeight: '60vh' }}
      data-testid="atw-delivery-setup-prompt"
    >
      <Stack alignItems="center" textAlign="center" sx={{ maxWidth: 480, width: '100%', p: 2 }}>
        <Stack gap={1}>
          <Typography variant="h5">{Messages.title}</Typography>
          <Typography variant="body1">{Messages.description}</Typography>
        </Stack>

        {/*
          The call to action slot. SEP has no guided ServiceNow form to send an
          operator to, so a regular user gets the explanation alone and an admin
          gets the settings page plus the name of the key to fill in.
        */}
        <Stack alignItems="center" gap={1.5} sx={{ my: 4 }}>
          <Typography variant="body1">{Messages.notConfigured}</Typography>
          {isAdmin && (
            <>
              <Typography variant="body2" color="text.secondary">
                {Messages.adminInstructions}
              </Typography>
              <Button
                variant="outlined"
                component={RouterLink}
                to={ROUTES.settings}
                data-testid="atw-delivery-setup-cta"
              >
                {Messages.openSettings}
              </Button>
            </>
          )}
        </Stack>

        <Stack gap={2}>
          <Typography variant="body2">
            {Messages.consentNote}{' '}
            <Link href={SUPPORT_DIAGNOSTICS_DOCS_URL} target="_blank" rel="noopener noreferrer">
              {Messages.howItWorks}
            </Link>
          </Typography>
          <Typography variant="body2">
            {Messages.subscriptionPrompt}
            <br />
            <Link href={PERCONA_SUPPORT_URL} target="_blank" rel="noopener noreferrer">
              {Messages.subscriptionLinkText}
            </Link>
          </Typography>
        </Stack>
      </Stack>
    </Stack>
  </Stack>
);

interface DeliverySetupGateProps {
  /** Whether the current user has admin privileges. Controls the call to action. */
  isAdmin?: boolean;
}

/**
 * Holds the Support diagnostics app until diagnostics delivery is configured.
 *
 * Anything the app can do ends in an upload to a ServiceNow case, so an
 * unconfigured deployment has nothing to offer but a dead end — the prompt
 * replaces the app rather than sitting beside it.
 *
 * A settings read that failed does *not* produce the prompt: the app renders
 * and reports its own failures, which is better than telling an operator with a
 * working connection to go configure one. That rule also covers the 403 the
 * admin-gated settings API returns to every regular user — "cannot tell" must
 * never become a permanent setup screen for people who could not clear it. A
 * build whose settings carry no `DIAGNOSTICS_DELIVERY_INPUTS` key at all is the
 * same case for a different reason: there is no key for anyone to fill in, so
 * the prompt would name a remedy nobody in this deployment can carry out.
 * `drifted` does gate: SEP holds values the current delivery plan no longer
 * accepts, so delivery is as broken as if nothing were stored.
 *
 * Note for the SEP → PMM sync: the PMM-embedded build wraps its ATW route in
 * its own `ServiceNowSetupGate` instead of using this one, because its call to
 * action opens a guided ServiceNow settings form that SEP does not have. The
 * two gates are knowingly divergent; the shared product copy lives in
 * `DeliverySetupGate.messages.ts` on this side and must be diffed against
 * PMM's `ServiceNowSetupGate.messages.ts` on every sync.
 */
export function DeliverySetupGate({
  isAdmin = false,
  children,
}: PropsWithChildren<DeliverySetupGateProps>) {
  const { status, stored, isLoading, error } = useDeliveryConfiguration();

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', p: 4 }}>
        <CircularProgress aria-label={Messages.loading} />
      </Box>
    );
  }

  if (error || !stored.isPresent || status === 'configured') {
    return <>{children}</>;
  }

  return <SetupPrompt isAdmin={isAdmin} />;
}
