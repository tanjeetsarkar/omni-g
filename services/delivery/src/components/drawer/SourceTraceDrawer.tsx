"use client";

import React, { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Calendar, Database, Cpu, ExternalLink } from "lucide-react";
import { useGraphExplorerStore } from "../../store/useGraphExplorerStore";
import type { CanvasNode } from "../../store/useGraphExplorerStore";

/**
 * V4 Track 1: responsive evidence drawer.
 *
 * - Desktop (>1024px): floating right sidebar panel, 380px wide, slide-in.
 * - Mobile (<767px): Framer Motion swipeable bottom sheet with drag-to-dismiss.
 *
 * Renders strictly human-readable provenance (source name, URL, timestamp,
 * plugin name) and the unmodified raw context snippet. Database UUIDs and
 * raw graph keys are never displayed.
 */

const MOBILE_BREAKPOINT = 767;
const DESKTOP_BREAKPOINT = 1024;

function useViewportWidth(): number {
  const [width, setWidth] = useState(
    typeof window === "undefined" ? DESKTOP_BREAKPOINT : window.innerWidth,
  );
  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return width;
}

/** Strip any UUID-like substrings (entity--/context-- prefixed) from display. */
function stripUuids(text: string): string {
  return text.replace(
    /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/g,
    "",
  );
}

function DrawerContent({
  node,
  onClose,
}: {
  node: CanvasNode;
  onClose: () => void;
}) {
  const source = node.source;
  const snippet = node.raw_context?.snippet_text ?? null;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-2">
          <Database size={16} className="text-indigo-400" />
          <h2 className="font-semibold text-sm text-slate-100">Source Trace</h2>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
          aria-label="Close drawer"
        >
          <X size={16} />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Name and Type */}
        <div>
          <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
            {node.entity_type}
          </span>
          <h3 className="text-lg font-bold text-slate-100 mt-2 break-words leading-snug">
            {node.entity_name}
          </h3>
        </div>

        {/* Provenance details */}
        <div className="bg-slate-950/50 rounded-lg p-3 border border-slate-800/80 space-y-2.5 text-xs">
          <div className="flex items-center justify-between">
            <span className="text-slate-500 flex items-center gap-1.5">
              <Cpu size={12} />
              Confidence
            </span>
            <span className="font-semibold text-indigo-400">
              {Number(node.confidence_score).toFixed(2)}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-slate-500 flex items-center gap-1.5">
              <Database size={12} />
              Source
            </span>
            <span className="font-medium text-slate-300 truncate max-w-[200px]">
              {source.source_name}
            </span>
          </div>
          {source.source_url && (
            <div className="flex items-center justify-between">
              <span className="text-slate-500 flex items-center gap-1.5">
                <ExternalLink size={12} />
                URL
              </span>
              <a
                href={source.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-cyan-400 hover:text-cyan-300 truncate max-w-[200px] underline"
                title={source.source_url}
              >
                {new URL(source.source_url).hostname}
              </a>
            </div>
          )}
          {source.mcp_plugin_name && (
            <div className="flex items-center justify-between">
              <span className="text-slate-500 flex items-center gap-1.5">
                <Database size={12} />
                Plugin
              </span>
              <span className="font-medium text-slate-300">
                {source.mcp_plugin_name}
              </span>
            </div>
          )}
          {source.ingested_at && (
            <div className="flex items-center justify-between">
              <span className="text-slate-500 flex items-center gap-1.5">
                <Calendar size={12} />
                Ingested
              </span>
              <span className="font-medium text-slate-300">
                {source.ingested_at.slice(0, 19).replace("T", " ")}
              </span>
            </div>
          )}
        </div>

        {/* Raw context snippet */}
        <div className="space-y-2">
          <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Raw Context / Source Evidence
          </h4>
          <div className="bg-slate-950/40 rounded-lg p-3 border border-slate-800 text-xs text-slate-300 leading-relaxed font-normal whitespace-pre-wrap select-all">
            {snippet ? (
              stripUuids(snippet)
            ) : (
              <span className="italic text-slate-500">
                No raw text context available for this node.
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export function SourceTraceDrawer() {
  const selectedNode = useGraphExplorerStore((s) => s.selectedNode);
  const selectNode = useGraphExplorerStore((s) => s.selectNode);
  const width = useViewportWidth();
  const isMobile = width <= MOBILE_BREAKPOINT;
  const isOpen = selectedNode !== null;

  const handleClose = () => selectNode(null);

  // Desktop: floating right sidebar
  if (!isMobile) {
    return (
      <AnimatePresence>
        {isOpen && selectedNode && (
          <motion.div
            key="desktop-drawer"
            initial={{ x: 380, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 380, opacity: 0 }}
            transition={{ type: "spring", damping: 30, stiffness: 300 }}
            className="absolute top-0 right-0 h-full w-[380px] bg-slate-900 border-l border-slate-800 text-slate-100 shadow-2xl z-50"
          >
            <DrawerContent node={selectedNode} onClose={handleClose} />
          </motion.div>
        )}
      </AnimatePresence>
    );
  }

  // Mobile: swipeable bottom sheet
  return (
    <AnimatePresence>
      {isOpen && selectedNode && (
        <>
          {/* Backdrop */}
          <motion.div
            key="mobile-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={handleClose}
            className="absolute inset-0 bg-black/50 z-40"
          />
          {/* Bottom sheet */}
          <motion.div
            key="mobile-sheet"
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            drag="y"
            dragConstraints={{ top: 0, bottom: 0 }}
            dragElastic={{ top: 0, bottom: 0.4 }}
            onDragEnd={(_, info) => {
              if (info.offset.y > 100) handleClose();
            }}
            transition={{ type: "spring", damping: 30, stiffness: 300 }}
            className="absolute bottom-0 left-0 right-0 max-h-[80vh] bg-slate-900 border-t border-slate-800 text-slate-100 shadow-2xl z-50 rounded-t-2xl"
          >
            {/* Drag handle */}
            <div className="flex justify-center pt-2 pb-1 shrink-0">
              <div className="w-10 h-1 rounded-full bg-slate-700" />
            </div>
            <DrawerContent node={selectedNode} onClose={handleClose} />
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
