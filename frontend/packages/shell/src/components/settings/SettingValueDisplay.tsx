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

import { useEffect, useRef, useState } from 'react';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import { Dialog, DialogTitle } from '@percona/percona-ui';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import Link from '@mui/material/Link';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import CheckIcon from '@mui/icons-material/Check';

import {
  formatSettingDisplayValue,
  formatSettingValuePretty,
  type SettingChoiceOption,
} from './settingField';

export interface SettingValueDisplayProps {
  /** The raw setting value to render. */
  value: unknown;
  /** The setting key, used for accessible labels on the modal. */
  settingKey: string;
  /** Optional enum/Literal options so the Current column can show labels. */
  options?: SettingChoiceOption[] | null;
}

/** Above this many characters the value is truncated behind a "View more" modal. */
const TRUNCATE_LIMIT = 200;

/** How long the "copied" confirmation tooltip stays visible, in ms. */
const COPIED_TOOLTIP_MS = 2000;

/**
 * Render a setting value for the read-only "Current" column. Long values are
 * truncated and revealed in full (pretty-printed JSON inside a `<pre>`) via a
 * modal so a single row can't blow up the layout.
 */
export default function SettingValueDisplay({
  value,
  settingKey,
  options,
}: SettingValueDisplayProps) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const copiedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const formatted = formatSettingDisplayValue(value, options);
  const isLong = formatted.length > TRUNCATE_LIMIT;
  const display = isLong ? `${formatted.slice(0, TRUNCATE_LIMIT)}…` : formatted;

  // Clear any pending tooltip timer on unmount so we don't setState after teardown.
  useEffect(() => {
    return () => {
      if (copiedTimer.current) {
        clearTimeout(copiedTimer.current);
      }
    };
  }, []);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(formatSettingValuePretty(value, options));
      setCopied(true);
      if (copiedTimer.current) {
        clearTimeout(copiedTimer.current);
      }
      copiedTimer.current = setTimeout(() => setCopied(false), COPIED_TOOLTIP_MS);
    } catch {
      // Clipboard write can be blocked (insecure context / denied permission);
      // silently no-op rather than surfacing a confusing confirmation.
    }
  };

  return (
    <>
      <Typography
        variant="body2"
        sx={{ fontFamily: 'monospace', overflowWrap: 'anywhere', wordBreak: 'break-word' }}
        data-testid={`setting-value-${settingKey}`}
      >
        {display}
      </Typography>
      {isLong ? (
        <Link
          component="button"
          type="button"
          variant="caption"
          underline="hover"
          onClick={() => setOpen(true)}
          sx={{ mt: 0.5 }}
        >
          View more…
        </Link>
      ) : null}

      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        fullWidth
        maxWidth="md"
        aria-labelledby={`setting-value-dialog-${settingKey}`}
      >
        <DialogTitle
          onClose={() => setOpen(false)}
          id={`setting-value-dialog-${settingKey}`}
          sx={{
            fontFamily: 'monospace',
            fontWeight: 600,
            backgroundColor: 'primary.main',
            color: 'primary.contrastText',
          }}
        >
          {settingKey}
        </DialogTitle>
        <DialogContent dividers>
          <Box
            component="pre"
            sx={{
              m: 0,
              fontFamily: 'monospace',
              fontSize: '0.8125rem',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              overflowWrap: 'anywhere',
            }}
          >
            {formatSettingValuePretty(value, options)}
          </Box>
        </DialogContent>
        <DialogActions>
          <Tooltip
            open={copied}
            disableFocusListener
            disableHoverListener
            disableTouchListener
            placement="top"
            title={
              <Stack direction="row" spacing={0.5} alignItems="center">
                <span>Value copied to clipboard</span>
                <CheckIcon fontSize="inherit" />
              </Stack>
            }
          >
            <Button variant="outlined" onClick={handleCopy}>
              Copy
            </Button>
          </Tooltip>
          <Button variant="contained" onClick={() => setOpen(false)}>
            Close
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
