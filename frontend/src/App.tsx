import { Box, Container, Flex, Heading, Text } from '@chakra-ui/react'
import { useState } from 'react'
import AboutModal from './components/AboutModal'
import ExportPanel from './components/ExportPanel'
import ImportButton from './components/ImportButton'
import type { ImportResponse } from './types'

type Mode = 'import' | 'export'

function App() {
  const [mode, setMode] = useState<Mode>('import')

  return (
    <Box className="app-backdrop" minH="100dvh">
      {/* Top brand bar — CAT yellow block with black wordmark, industrial and terse. */}
      <Box as="header" bg="cat.yellow" borderBottomWidth="2px" borderColor="ink">
        <Container maxW="5xl">
          <Flex align="center" gap="3" py="3">
            <Text
              as="span"
              bg="ink"
              color="cat.yellow"
              px="2"
              py="1"
              fontFamily="heading"
              fontSize="lg"
              fontWeight="700"
              lineHeight="1"
            >
              AMT
            </Text>
            <Text
              as="span"
              color="ink"
              fontFamily="heading"
              fontSize="xl"
              fontWeight="700"
              lineHeight="1"
              letterSpacing="tight"
            >
              CYCLE WORKBENCH
            </Text>
            {/* Secondary action (outline on yellow) */}
            <AboutModal />
          </Flex>
        </Container>
      </Box>

      <Container maxW="5xl" py={{ base: 10, md: 16 }}>
        <Box maxW="2xl" mx="auto">
          {/* Segmented control */}
          <Flex
            role="tablist"
            aria-label="Workbench mode"
            mb="6"
            borderRadius="sm"
            borderWidth="1px"
            borderColor="ink"
            overflow="hidden"
            display="inline-flex"
          >
            <Box
              as="button"
              role="tab"
              aria-selected={mode === 'import'}
              onClick={() => setMode('import')}
              px="4"
              py="2"
              fontFamily="heading"
              fontWeight="700"
              fontSize="sm"
              lineHeight="1"
              cursor="pointer"
              border="none"
              borderRightWidth="1px"
              borderColor="ink"
              bg={mode === 'import' ? 'ink' : 'white'}
              color={mode === 'import' ? 'cat.yellow' : 'ink'}
              _hover={mode === 'import' ? {} : { bg: 'line' }}
              _focusVisible={{ outline: '2px solid', outlineColor: 'link', outlineOffset: '1px' }}
              transition="background 0.15s, color 0.15s"
            >
              Import Raw Data
            </Box>
            <Box
              as="button"
              role="tab"
              aria-selected={mode === 'export'}
              onClick={() => setMode('export')}
              px="4"
              py="2"
              fontFamily="heading"
              fontWeight="700"
              fontSize="sm"
              lineHeight="1"
              cursor="pointer"
              border="none"
              bg={mode === 'export' ? 'ink' : 'white'}
              color={mode === 'export' ? 'cat.yellow' : 'ink'}
              _hover={mode === 'export' ? {} : { bg: 'line' }}
              _focusVisible={{ outline: '2px solid', outlineColor: 'link', outlineOffset: '1px' }}
              transition="background 0.15s, color 0.15s"
            >
              Export from Database
            </Box>
          </Flex>

          {/* Heading + subtitle change per mode */}
          <Heading
            as="h1"
            fontFamily="heading"
            fontWeight="700"
            fontSize="2xl"
            lineHeight="1"
            letterSpacing="tight"
            color="ink"
          >
            {mode === 'import' ? 'Import Raw Data' : 'Export from Database'}
          </Heading>
          <Text mt="2" fontSize="md" color="muted">
            {mode === 'import'
              ? 'Import raw telemetry files and generate simulation files.'
              : 'Generate simulation files from an existing database site.'}
          </Text>

          <Box mt="6">
            {mode === 'import' ? (
              <ImportButton
                onImportComplete={(_data: ImportResponse) => {
                  // Import/export completion is reflected in ImportButton's own UI
                  // (status + download buttons). No additional handling needed here.
                }}
              />
            ) : (
              <ExportPanel />
            )}
          </Box>
        </Box>
      </Container>
    </Box>
  )
}

export default App
