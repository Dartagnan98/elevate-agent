/**
 * Dashboard Plugin SDK + Registry
 *
 * Exposes React, UI components, hooks, and utilities on the window so
 * that plugin bundles can use them without bundling their own copies.
 *
 * Plugins call window.__ELEVATE_PLUGINS__.register(name, Component)
 * to register their tab component.
 */

import React, {
  useState,
  useEffect,
  useCallback,
  useMemo,
  useRef,
  useContext,
  createContext,
} from "react";
import { api, fetchJSON } from "@/lib/api";
import { cn, timeAgo, isoTimeAgo } from "@/lib/utils";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectOption } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useI18n } from "@/i18n";
import { registerSlot, PluginSlot } from "./slots";

// ---------------------------------------------------------------------------
// Plugin registry — plugins call register() to add their component.
// ---------------------------------------------------------------------------

type RegistryListener = () => void;

const _registered: Map<string, React.ComponentType> = new Map();
const _loadErrors: Map<string, string> = new Map();
const _listeners: Set<RegistryListener> = new Set();

function _notify() {
  for (const fn of _listeners) {
    try { fn(); } catch { /* ignore */ }
  }
}

/** Re-run registry subscribers (e.g. after a plugin script onload, or dev HMR re-inject). */
export function notifyPluginRegistry() {
  _notify();
}

/** Register a plugin component. Called by plugin JS bundles. */
function registerPlugin(name: string, component: React.ComponentType) {
  _loadErrors.delete(name);
  _registered.set(name, component);
  _notify();
}

/** Get a registered component by plugin name. */
export function getPluginComponent(name: string): React.ComponentType | undefined {
  return _registered.get(name);
}

export function getPluginLoadError(name: string): string | undefined {
  return _loadErrors.get(name);
}

export function setPluginLoadError(name: string, message: string) {
  _loadErrors.set(name, message);
  _notify();
}

/** Subscribe to registry changes (returns unsubscribe fn). */
export function onPluginRegistered(fn: RegistryListener): () => void {
  _listeners.add(fn);
  return () => _listeners.delete(fn);
}

/** Get current count of registered plugins. */
export function getRegisteredCount(): number {
  return _registered.size;
}

// ---------------------------------------------------------------------------
// Expose SDK + registry on window
// ---------------------------------------------------------------------------

declare global {
  interface Window {
    __ELEVATE_PLUGIN_SDK__: unknown;
    __ELEVATE_PLUGINS__: {
      register: typeof registerPlugin;
      registerSlot: typeof registerSlot;
    };
    // Legacy Hermes-era global names. Shipped plugin bundles
    // (example-dashboard, strike-freedom-cockpit) still read these; keep
    // them aliased to the Elevation globals until those bundles are rebuilt.
    __HERMES_PLUGIN_SDK__?: unknown;
    __HERMES_PLUGINS__?: {
      register: typeof registerPlugin;
      registerSlot: typeof registerSlot;
    };
  }
}

export function exposePluginSDK() {
  window.__ELEVATE_PLUGINS__ = {
    register: registerPlugin,
    registerSlot,
  };

  window.__ELEVATE_PLUGIN_SDK__ = {
    // React core — plugins use these instead of importing react
    React,
    hooks: {
      useState,
      useEffect,
      useCallback,
      useMemo,
      useRef,
      useContext,
      createContext,
    },

    // Elevation API client
    api,
    // Raw fetchJSON for plugin-specific endpoints
    fetchJSON,

    // UI components (shadcn/ui primitives)
    components: {
      Card,
      CardHeader,
      CardTitle,
      CardContent,
      Badge,
      Button,
      Input,
      Label,
      Select,
      SelectOption,
      Separator,
      Tabs,
      TabsList,
      TabsTrigger,
      PluginSlot,
    },

    // Utilities
    utils: { cn, timeAgo, isoTimeAgo },

    // Hooks
    useI18n,
  };

  // Backward-compat: shipped plugin bundles still destructure the legacy
  // Hermes globals. Without these aliases every route throws
  // "Cannot destructure property 'React' of 'SDK' as it is undefined"
  // and the plugin system (incl. the strike-freedom-cockpit slot) is dead.
  window.__HERMES_PLUGINS__ = window.__ELEVATE_PLUGINS__;
  window.__HERMES_PLUGIN_SDK__ = window.__ELEVATE_PLUGIN_SDK__;
}
