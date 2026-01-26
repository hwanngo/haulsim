import {
  Badge,
  Box,
  Button,
  Dialog,
  Flex,
  Heading,
  IconButton,
  Portal,
  Separator,
  Text,
} from '@chakra-ui/react'
import type { ReactElement, ReactNode } from 'react'

type IconProps = { size?: number }
type IconFn = (p?: IconProps) => ReactElement

// SVG icons (no emoji), single stroke family — matches ImportButton's icon set.
const svg =
  (paths: ReactNode): IconFn =>
  (p) => (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      width={p?.size ?? 18}
      height={p?.size ?? 18}
      aria-hidden="true"
    >
      {paths}
    </svg>
  )

const Icon: Record<string, IconFn> = {
  help: svg(
    <>
      <circle cx="12" cy="12" r="10" />
      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </>,
  ),
  close: svg(
    <>
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </>,
  ),
  flow: svg(
    <>
      <path d="M3 3v18h18" />
      <path d="M18 17V9" />
      <path d="M13 17V5" />
      <path d="M8 17v-3" />
    </>,
  ),
  steps: svg(
    <>
      <path d="M9 11l3 3L22 4" />
      <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
    </>,
  ),
  file: svg(
    <>
      <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
      <polyline points="14 2 14 8 20 8" />
    </>,
  ),
  book: svg(
    <>
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
    </>,
  ),
}

// Numbered "how to use" steps. The visual badge is decorative (aria-hidden);
// the surrounding <ol> carries the real ordering for screen readers.
const STEPS: Array<{ title: string; desc: string }> = [
  {
    title: 'Pick what to export',
    desc: 'Toggle Model, Simulation, and/or Routes Excel. At least one stays on.',
  },
  {
    title: 'Add your data',
    desc: 'Drag a single .zip of gateway telemetry onto the dropzone, or click to browse.',
  },
  {
    title: 'Watch it run',
    desc: 'The status panel moves through Uploading → Parsing → Processing.',
  },
  { title: 'Download', desc: 'When it reads Completed, download the generated files.' },
]

const OUTPUTS: Array<{ icon: IconFn; label: string; ext: string; desc: string }> = [
  { icon: Icon.file, label: 'Model', ext: 'JSON', desc: 'Site structure and configuration.' },
  {
    icon: Icon.flow,
    label: 'DES Inputs',
    ext: 'JSON',
    desc: 'Discrete-event simulation inputs and events.',
  },
  { icon: Icon.file, label: 'Ledger', ext: 'JSON', desc: 'Per-cycle event record.' },
  {
    icon: Icon.file,
    label: 'Routes Excel',
    ext: 'XLSX',
    desc: 'Haul routes in editable template form.',
  },
]

const GLOSSARY: Array<{ term: string; desc: string }> = [
  {
    term: 'Gateway telemetry',
    desc: 'Raw position and status records logged by on-board units on each machine.',
  },
  { term: 'Cycle', desc: 'One load → haul → dump → return trip made by a truck.' },
  {
    term: 'Load / Dump zone',
    desc: 'Clustered areas where trucks are loaded or where they dump material.',
  },
  { term: 'Haul route', desc: 'The connected road segments a truck travels between zones.' },
  {
    term: 'DES',
    desc: 'Discrete-Event Simulation — models the operation as a sequence of timestamped events.',
  },
]

function SectionHeading({ icon, children }: { icon: IconFn; children: ReactNode }) {
  return (
    <Flex align="center" gap="2" mb="3" color="ink">
      <Box color="cat.yellowEdge">{icon({ size: 16 })}</Box>
      <Heading
        as="h3"
        fontFamily="heading"
        fontWeight="700"
        fontSize="md"
        lineHeight="1"
        letterSpacing="tight"
        color="ink"
      >
        {children}
      </Heading>
    </Flex>
  )
}

function AboutModal() {
  return (
    <Dialog.Root
      size="lg"
      placement="center"
      scrollBehavior="inside"
      motionPreset="scale"
      role="dialog"
    >
      <Dialog.Trigger asChild>
        <Button
          size="sm"
          h="9"
          px="3"
          gap="1.5"
          ml="auto"
          flexShrink="0"
          bg="transparent"
          color="ink"
          borderWidth="1px"
          borderColor="ink"
          borderRadius="sm"
          fontFamily="heading"
          fontWeight="700"
          letterSpacing="tight"
          textTransform="uppercase"
          _hover={{ bg: 'ink', color: 'cat.yellow' }}
          _focusVisible={{ outline: '2px solid', outlineColor: 'ink', outlineOffset: '2px' }}
        >
          {Icon.help({ size: 16 })}
          <Box as="span" display={{ base: 'none', sm: 'inline' }}>
            How to use
          </Box>
        </Button>
      </Dialog.Trigger>

      <Portal>
        {/* Scrim uses the design system's "overlay" token (soft translucent black,
            minimal/non-glossy elevation language — no decorative blur). */}
        <Dialog.Backdrop bg="overlay" />
        <Dialog.Positioner p="4">
          <Dialog.Content
            bg="white"
            borderRadius="lg"
            borderWidth="1px"
            borderColor="ink"
            boxShadow="md"
            overflow="hidden"
            maxW="2xl"
            w="full"
          >
            {/* Header — black band with CAT-yellow accent, mirrors the app's card header. */}
            <Dialog.Header bg="ink" px="5" py="4" borderBottomWidth="2px" borderColor="cat.yellow">
              <Flex align="center" gap="3">
                <Text
                  as="span"
                  bg="cat.yellow"
                  color="ink"
                  px="2"
                  py="1"
                  fontFamily="heading"
                  fontSize="md"
                  fontWeight="700"
                  lineHeight="1"
                  borderRadius="sm"
                >
                  AMT
                </Text>
                <Dialog.Title
                  fontFamily="heading"
                  fontWeight="700"
                  fontSize="lg"
                  lineHeight="1.15"
                  letterSpacing="tight"
                  color="white"
                >
                  How to use the AMT Cycle Workbench
                </Dialog.Title>
              </Flex>
            </Dialog.Header>

            <Dialog.Body px="5" py="5">
              {/* Purpose — doubles as the dialog's accessible description. */}
              <Dialog.Description fontSize="md" color="ink" lineHeight="1.6" mb="6">
                The <b>AMT Cycle Workbench</b> turns raw mine-haulage gateway telemetry into
                ready-to-run simulation inputs. Upload a ZIP of gateway files and it reconstructs
                truck cycles, load/dump zones, and haul routes, then exports a site model and
                discrete-event simulation (DES) files.
              </Dialog.Description>

              {/* Steps */}
              <SectionHeading icon={Icon.steps}>Four steps</SectionHeading>
              <Box as="ol" listStyleType="none" m="0" p="0" mb="6">
                {STEPS.map((s, i) => (
                  <Flex
                    as="li"
                    key={s.title}
                    align="flex-start"
                    gap="3"
                    mb={i === STEPS.length - 1 ? '0' : '3'}
                  >
                    <Flex
                      aria-hidden="true"
                      flexShrink="0"
                      align="center"
                      justify="center"
                      h="7"
                      w="7"
                      borderRadius="sm"
                      bg="cat.yellow"
                      color="ink"
                      fontFamily="heading"
                      fontWeight="700"
                      fontSize="md"
                      lineHeight="1"
                    >
                      {i + 1}
                    </Flex>
                    <Box>
                      <Text
                        fontFamily="heading"
                        fontWeight="700"
                        fontSize="md"
                        lineHeight="1.3"
                        color="ink"
                      >
                        {s.title}
                      </Text>
                      <Text fontSize="sm" color="muted" lineHeight="1.5">
                        {s.desc}
                      </Text>
                    </Box>
                  </Flex>
                ))}
              </Box>

              <Separator borderColor="line" mb="6" />

              {/* Outputs */}
              <SectionHeading icon={Icon.file}>What you get</SectionHeading>
              <Box mb="6">
                {OUTPUTS.map((o, i) => (
                  <Flex
                    key={o.label}
                    align="flex-start"
                    gap="3"
                    mb={i === OUTPUTS.length - 1 ? '0' : '2.5'}
                  >
                    <Box color="muted" mt="0.5" flexShrink="0">
                      {o.icon({ size: 16 })}
                    </Box>
                    <Box>
                      <Flex align="center" gap="2">
                        <Text fontFamily="heading" fontWeight="700" fontSize="sm" color="ink">
                          {o.label}
                        </Text>
                        <Badge
                          bg="line"
                          color="muted"
                          fontSize="2xs"
                          fontWeight="700"
                          px="1.5"
                          borderRadius="sm"
                          textTransform="none"
                        >
                          {o.ext}
                        </Badge>
                      </Flex>
                      <Text fontSize="sm" color="muted" lineHeight="1.5">
                        {o.desc}
                      </Text>
                    </Box>
                  </Flex>
                ))}
              </Box>

              <Separator borderColor="line" mb="6" />

              {/* Glossary — real definition-list semantics (dl/dt/dd). */}
              <SectionHeading icon={Icon.book}>Glossary</SectionHeading>
              <Box as="dl" m="0">
                {GLOSSARY.map((g, i) => (
                  <Box key={g.term} mb={i === GLOSSARY.length - 1 ? '0' : '3'}>
                    <Text as="dt" fontFamily="heading" fontWeight="700" fontSize="sm" color="ink">
                      {g.term}
                    </Text>
                    <Text as="dd" m="0" fontSize="sm" color="muted" lineHeight="1.5">
                      {g.desc}
                    </Text>
                  </Box>
                ))}
              </Box>
            </Dialog.Body>

            <Dialog.Footer px="5" py="4" borderTopWidth="1px" borderColor="line" gap="3">
              <Text fontSize="xs" color="muted" mr="auto">
                Proof of concept — for learning and experimentation.
              </Text>
              <Dialog.ActionTrigger asChild>
                <Button
                  size="sm"
                  h="9"
                  px="4"
                  bg="cat.yellow"
                  color="ink"
                  borderRadius="md"
                  fontFamily="heading"
                  fontWeight="700"
                  letterSpacing="tight"
                  _hover={{ bg: 'cat.yellowEdge', color: 'white' }}
                  _focusVisible={{
                    outline: '2px solid',
                    outlineColor: 'link',
                    outlineOffset: '2px',
                  }}
                >
                  Got it
                </Button>
              </Dialog.ActionTrigger>
            </Dialog.Footer>

            {/* Corner close (X) — second escape route alongside ESC and the scrim. */}
            <Dialog.CloseTrigger asChild>
              <IconButton
                aria-label="Close"
                size="sm"
                position="absolute"
                top="3"
                right="3"
                bg="transparent"
                color="white"
                borderRadius="sm"
                _hover={{ bg: 'whiteAlpha.300' }}
                _focusVisible={{
                  outline: '2px solid',
                  outlineColor: 'cat.yellow',
                  outlineOffset: '2px',
                }}
              >
                {Icon.close({ size: 18 })}
              </IconButton>
            </Dialog.CloseTrigger>
          </Dialog.Content>
        </Dialog.Positioner>
      </Portal>
    </Dialog.Root>
  )
}

export default AboutModal
