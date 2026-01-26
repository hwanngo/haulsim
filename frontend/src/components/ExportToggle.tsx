import { Box, Flex, Text } from '@chakra-ui/react'
import type { KeyboardEvent, ReactElement } from 'react'

// Icon render function: takes an optional size, returns an SVG element.
export type IconProps = { size?: number }
export type IconFn = (p?: IconProps) => ReactElement

export interface ExportToggleProps {
  icon: IconFn
  label: string
  desc: string
  checked: boolean
  disabled: boolean
  onToggle: () => void
}

// CAT-styled switch row used by both the Import and Export panels.
// Behaviour and styling are identical to the previous per-file copies (extracted
// to remove duplication); see Stream F (C-f3).
export function ExportToggle({
  icon,
  label,
  desc,
  checked,
  disabled,
  onToggle,
}: ExportToggleProps) {
  return (
    <Box
      role="switch"
      aria-checked={checked}
      aria-disabled={disabled}
      aria-label={`${label}: ${desc}`}
      tabIndex={disabled ? -1 : 0}
      onClick={() => {
        if (!disabled) onToggle()
      }}
      onKeyDown={(e: KeyboardEvent) => {
        if (!disabled && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault()
          onToggle()
        }
      }}
      display="flex"
      alignItems="center"
      justifyContent="space-between"
      gap="3"
      w="full"
      textAlign="left"
      p="3"
      borderRadius="md"
      borderWidth="1px"
      transition="background 0.15s, border-color 0.15s, opacity 0.15s"
      cursor={disabled ? 'not-allowed' : 'pointer'}
      opacity={disabled ? 0.6 : 1}
      bg={checked ? 'rgba(255,205,17,0.10)' : 'white'}
      borderColor={checked ? 'cat.yellowEdge' : 'line'}
      _hover={disabled ? {} : { borderColor: checked ? 'cat.yellowEdge' : 'blackAlpha.400' }}
      _focusVisible={{ outline: '2px solid', outlineColor: 'link', outlineOffset: '1px' }}
    >
      <Flex align="center" gap="3" minW="0">
        <Flex
          align="center"
          justify="center"
          h="9"
          w="9"
          flexShrink="0"
          borderRadius="md"
          bg={checked ? 'cat.yellow' : 'line'}
          color={checked ? 'ink' : 'muted'}
        >
          {icon({ size: 18 })}
        </Flex>
        <Box minW="0">
          <Text fontFamily="heading" fontWeight="700" fontSize="md" lineHeight="1.2" color="ink">
            {label}
          </Text>
          <Text fontSize="sm" color="muted" truncate>
            {desc}
          </Text>
        </Box>
      </Flex>
      {/* Visual switch (state mirrors aria-checked on the parent). */}
      <Box
        position="relative"
        h="6"
        w="11"
        flexShrink="0"
        borderRadius="full"
        transition="background 0.15s"
        bg={checked ? 'cat.yellow' : 'line'}
      >
        <Box
          position="absolute"
          top="2px"
          left={checked ? '22px' : '2px'}
          h="5"
          w="5"
          borderRadius="full"
          bg="white"
          borderWidth="1px"
          borderColor="line"
          transition="left 0.15s"
        />
      </Box>
    </Box>
  )
}

export default ExportToggle
