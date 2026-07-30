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

import { lazy, Suspense } from 'react';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import Accordion from '@mui/material/Accordion';
import AccordionDetails from '@mui/material/AccordionDetails';
import AccordionSummary from '@mui/material/AccordionSummary';
import Box from '@mui/material/Box';
import Skeleton from '@mui/material/Skeleton';
import Typography from '@mui/material/Typography';
import { detailSyntaxBlockSx } from '@sep/framework';
import type { TaskDetailTask } from './types';

const DetailSyntaxHighlighter = lazy(() =>
  import('@sep/framework').then((mod) => ({ default: mod.DetailSyntaxHighlighter })),
);

interface TaskSpecificationSectionProps {
  task: TaskDetailTask;
}

const taskSpecificationSyntaxSx = { maxHeight: 400, overflowY: 'auto' } as const;

const syntaxFallback = (
  <Skeleton
    variant="rectangular"
    height={120}
    sx={{ ...detailSyntaxBlockSx, ...taskSpecificationSyntaxSx, mt: 0.5 }}
  />
);

export function TaskSpecificationSection({ task }: TaskSpecificationSectionProps) {
  return (
    <Box component="fieldset" sx={{ border: 0, p: 0, mb: 3 }}>
      <Accordion defaultExpanded disableGutters slotProps={{ transition: { unmountOnExit: true } }}>
        <AccordionSummary
          expandIcon={<ExpandMoreIcon />}
          sx={{
            pl: 2,
            pr: 1,
            minHeight: 48,
            '& .MuiAccordionSummary-content': { my: 1 },
          }}
        >
          <Typography component="legend" variant="subtitle1" sx={{ fontWeight: 600 }}>
            Specification
          </Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ px: 0, pl: 2, pr: 2, pt: 0, pb: 2 }}>
          <Suspense fallback={syntaxFallback}>
            <Box sx={taskSpecificationSyntaxSx}>
              <DetailSyntaxHighlighter value={task} language="json" />
            </Box>
          </Suspense>
        </AccordionDetails>
      </Accordion>
    </Box>
  );
}
