import LinkIcon from '@mui/icons-material/Link';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';

export interface ChainDisplayProps {
  chainNames?: readonly string[] | null;
  /** When chainNames is empty but the task is part of a chain, depth > 0 renders a fallback link icon. */
  chainDepth?: number | null;
  onChainItemClick?: (name: string, index: number) => void;
}

export function ChainDisplay({ chainNames, chainDepth, onChainItemClick }: ChainDisplayProps) {
  if (chainNames && chainNames.length > 0) {
    return (
      <Box
        component="span"
        sx={{
          display: 'inline-flex',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 0.5,
        }}
        data-testid="chain-display"
      >
        {chainNames.map((name, index) => (
          <Box
            key={`${name}-${index}`}
            component="span"
            sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}
          >
            <Chip
              size="small"
              label={name}
              variant="outlined"
              clickable={!!onChainItemClick}
              onClick={onChainItemClick ? () => onChainItemClick(name, index) : undefined}
            />
            {index < chainNames.length - 1 && (
              <Typography component="span" variant="body2" aria-hidden>
                →
              </Typography>
            )}
          </Box>
        ))}
      </Box>
    );
  }

  if (typeof chainDepth === 'number' && chainDepth > 0) {
    return (
      <Tooltip title={`Chained task (depth: ${chainDepth})`}>
        <LinkIcon fontSize="small" data-testid="chain-depth-icon" />
      </Tooltip>
    );
  }

  return (
    <Typography component="span" variant="body2" color="text.secondary">
      —
    </Typography>
  );
}
