import Badge from '@mui/material/Badge';
import Tab from '@mui/material/Tab';
import Tabs from '@mui/material/Tabs';

export interface LogStepTabsProps {
  steps: string[];
  activeStep: string | undefined;
  unreadSteps: Set<string>;
  onSelect: (step: string) => void;
}

export function LogStepTabs({ steps, activeStep, unreadSteps, onSelect }: LogStepTabsProps) {
  if (steps.length === 0) {
    return null;
  }

  // Clamp to a valid step so MUI Tabs doesn't warn when activeStep tracks a
  // different set (e.g. log steps vs execution-event steps).
  const resolvedValue =
    activeStep !== undefined && steps.includes(activeStep) ? activeStep : steps[0];

  return (
    <Tabs
      value={resolvedValue}
      onChange={(_, value: string) => onSelect(value)}
      variant="scrollable"
      scrollButtons="auto"
      sx={{ minHeight: 36, '& .MuiTab-root': { minHeight: 36, py: 0.5 } }}
    >
      {steps.map((step) => (
        <Tab
          key={step}
          value={step}
          label={
            <Badge
              color="primary"
              variant="dot"
              invisible={!unreadSteps.has(step) || step === activeStep}
              sx={{ '& .MuiBadge-badge': { right: -8, top: 2 } }}
            >
              <span>{step}</span>
            </Badge>
          }
        />
      ))}
    </Tabs>
  );
}
