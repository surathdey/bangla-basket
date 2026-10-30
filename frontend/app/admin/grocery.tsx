import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Image,
  TextInput, ScrollView, Modal, Platform,
} from "react-native";
import { useRouter } from "expo-router";
import Ionicons from "@react-native-vector-icons/ionicons";
import AdminShell from "@/src/components/AdminShell";
import { adminApi, getAdminToken } from "@/src/adminApi";
import { getBackendUrl } from "@/src/utils/backendUrl";
import { colors, spacing, radius, shadows } from "@/src/theme";

type Variant = {
  variant_id: string; title: string; price_cents: number; compare_at_cents: number;
  available: boolean; sku?: string; weight_g?: number;
};
type Grocery = {
  item_id: string; title: string; handle: string; description: string; category: string;
  subcategory?: string;
  price_cents: number; compare_at_cents: number; unit: string; image_url: string;
  images: string[]; vendor: string; tags: string[]; in_stock: boolean;
  is_active: boolean; is_featured: boolean; sort_order: number; source_id: string;
  variants?: Variant[]; has_variants?: boolean; all_categories?: string; on_sale?: boolean; product_url?: string;
};

// Editable variant row (prices held as strings while typing).
type VEdit = { variant_id: string; title: string; priceStr: string; compareStr: string; available: boolean; sku: string; weight_g: number };

// Canonical category list — the restructured "Fresh" meat/fish/veg categories
// come first, followed by pantry categories.
const CATEGORIES = [
  "Fresh Beef", "Fresh Chicken", "Fresh Fish", "Fresh Goat", "Fresh Lamb", "Fresh Vegetable",
  "Beauty & Personal Care", "Beverage", "Bulk Savings",
  "Canned Essentials", "Cleaning Supplies", "Condiment", "Dry Fish",
  "Frozen Snacks", "Frozen Sweets", "Frozen Vegetable/Fruits",
  "Grains", "Heat & Eat (Frozen Ready Delights)", "Herb & Health",
  "Noodles & Instant Food", "Oil & Ghee", "Paan Supari Corner", "Pickles",
  "Quick Cook", "Ready Mix Masala", "Snacks", "Spice", "Vegetable & Fruit Seeds",
];

// Sub-categories available per category. Only Fresh Fish uses them today.
const SUBCATEGORIES: Record<string, string[]> = {
  "Fresh Fish": ["Block", "Cut", "By Weight"],
};

const rndId = () => `gr_${Math.random().toString(36).slice(2, 12)}`;
const rndVarId = () => `v_${Math.random().toString(36).slice(2, 14)}`;
const blank = (): Grocery => ({
  item_id: rndId(), title: "", handle: "", description: "", category: "Fresh Fish", subcategory: "",
  price_cents: 0, compare_at_cents: 0, unit: "", image_url: "", images: [], vendor: "",
  tags: [], in_stock: true, is_active: true, is_featured: false, sort_order: 0, source_id: "",
  variants: [], has_variants: false,
});

export default function AdminGrocery() {
  const router = useRouter();
  const [items, setItems] = useState<Grocery[]>([]);
  const [cats, setCats] = useState<string[]>([]);
  const [cat, setCat] = useState("All");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [edit, setEdit] = useState<Grocery | null>(null);
  const [priceStr, setPriceStr] = useState("");
  const [compareStr, setCompareStr] = useState("");
  const [variants, setVariants] = useState<VEdit[]>([]);
  const [catPickerOpen, setCatPickerOpen] = useState(false);
  const [busy, setBusy] = useState("");
  // Bulk recategorize
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [moveTarget, setMoveTarget] = useState("");
  const [movePickerOpen, setMovePickerOpen] = useState(false);
  const [moving, setMoving] = useState(false);
  // In-app delete confirmation (window.confirm is suppressed inside the
  // preview iframe, which made the trash icon appear to "do nothing").
  const [confirmDel, setConfirmDel] = useState<Grocery | null>(null);
  const [deleting, setDeleting] = useState(false);
  // Per-row import errors surfaced from the Excel upload.
  const [importErrors, setImportErrors] = useState<{ row: number; reason: string }[]>([]);

  const loadCats = useCallback(async () => {
    const r = await adminApi.get<{ categories: { category: string }[] }>("/grocery/categories" as any);
    // categories endpoint is public; call via public path
  }, []);

  const load = useCallback(async (pg: number) => {
    setLoading(true);
    const params = new URLSearchParams({ page: String(pg), limit: "30" });
    if (cat !== "All") params.set("category", cat);
    if (query) params.set("q", query);
    const r = await adminApi.get<{ items: Grocery[]; pages: number; total: number }>(`/admin/grocery?${params.toString()}`);
    if (r.status === 401) { router.replace("/admin"); return; }
    if (r.ok) { setItems(r.data.items || []); setPages(r.data.pages); setTotal(r.data.total); setPage(pg); }
    setLoading(false);
  }, [cat, query, router]);

  useEffect(() => {
    (async () => {
      const t = await getAdminToken();
      if (!t) return router.replace("/admin");
      const c = await fetch(`${getBackendUrl()}/api/grocery/categories`).then(r => r.json()).catch(() => null);
      if (c?.categories) setCats(c.categories.map((x: any) => x.category));
      await load(1);
    })();
  }, [router, load]);

  useEffect(() => { load(1); }, [cat, query, load]);

  const openEdit = (g: Grocery | null) => {
    const t = g ? JSON.parse(JSON.stringify(g)) : blank();
    setEdit(t);
    setCatPickerOpen(false);
    setPriceStr((t.price_cents / 100).toFixed(2));
    setCompareStr(t.compare_at_cents ? (t.compare_at_cents / 100).toFixed(2) : "");
    const vs: Variant[] = Array.isArray(t.variants) ? t.variants : [];
    setVariants(vs.map(v => ({
      variant_id: v.variant_id || rndVarId(),
      title: v.title || "Standard",
      priceStr: ((v.price_cents || 0) / 100).toFixed(2),
      compareStr: v.compare_at_cents ? ((v.compare_at_cents / 100).toFixed(2)) : "",
      available: v.available !== false,
      sku: v.sku || "",
      weight_g: v.weight_g || 0,
    })));
  };

  const addVariant = () => setVariants(prev => [...prev, { variant_id: rndVarId(), title: "", priceStr: priceStr || "0.00", compareStr: "", available: true, sku: "", weight_g: 0 }]);
  const patchVariant = (i: number, patch: Partial<VEdit>) => setVariants(prev => prev.map((v, idx) => idx === i ? { ...v, ...patch } : v));
  const removeVariant = (i: number) => setVariants(prev => prev.filter((_, idx) => idx !== i));

  const save = async () => {
    if (!edit) return;
    if (!edit.title.trim()) return;
    const cleanVariants = variants.filter(v => v.title.trim());
    const body: any = { ...edit };
    if (cleanVariants.length > 0) {
      const outVars: Variant[] = cleanVariants.map(v => ({
        variant_id: v.variant_id,
        title: v.title.trim(),
        price_cents: Math.round((parseFloat(v.priceStr) || 0) * 100),
        compare_at_cents: Math.round((parseFloat(v.compareStr) || 0) * 100),
        available: v.available,
        sku: v.sku,
        weight_g: v.weight_g,
      }));
      const priced = outVars.filter(v => v.price_cents > 0);
      const availPriced = priced.filter(v => v.available);
      const source = availPriced.length ? availPriced : (priced.length ? priced : outVars);
      const pick = source.reduce((m, v) => (v.price_cents < m.price_cents ? v : m), source[0]);
      body.variants = outVars;
      body.has_variants = outVars.length > 1 || outVars[0].title.toLowerCase() !== "standard";
      body.price_cents = pick ? pick.price_cents : 0;
      body.compare_at_cents = pick ? pick.compare_at_cents : 0;
      body.in_stock = outVars.some(v => v.available);
    } else {
      body.variants = [];
      body.has_variants = false;
      body.price_cents = Math.round((parseFloat(priceStr) || 0) * 100);
      body.compare_at_cents = Math.round((parseFloat(compareStr) || 0) * 100);
    }
    const r = await adminApi.post("/admin/grocery", body);
    if (r.ok) { setEdit(null); await load(page); }
  };

  const remove = async (g: Grocery) => {
    setConfirmDel(g);
  };

  const doDelete = async () => {
    if (!confirmDel) return;
    setDeleting(true);
    const r = await adminApi.del(`/admin/grocery/${confirmDel.item_id}`);
    setDeleting(false);
    setConfirmDel(null);
    if (r.ok) await load(page);
  };

  // ---- Bulk recategorize ----
  const toggleSelect = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const selectAllOnPage = () => setSelected(prev => {
    const next = new Set(prev);
    items.forEach(i => next.add(i.item_id));
    return next;
  });
  const clearSelection = () => setSelected(new Set());
  const exitSelectMode = () => { setSelectMode(false); setSelected(new Set()); setMovePickerOpen(false); setMoveTarget(""); };

  const applyBulkMove = async () => {
    if (!moveTarget || selected.size === 0) return;
    setMoving(true);
    const r = await adminApi.post<{ modified: number }>("/admin/grocery/bulk-recategorize", {
      item_ids: Array.from(selected),
      target_category: moveTarget,
    });
    setMoving(false);
    if (r.ok) {
      const n = r.data?.modified ?? selected.size;
      if (Platform.OS === "web") window.alert(`Moved ${n} item(s) to "${moveTarget}".`);
      exitSelectMode();
      await load(page);
    } else if (Platform.OS === "web") {
      window.alert("Could not move items. Please try again.");
    }
  };

  const pickImage = async () => {
    if (!edit || Platform.OS !== "web") return;
    const input = document.createElement("input");
    input.type = "file"; input.accept = "image/*";
    input.onchange = async (e: any) => {
      const file = e.target.files?.[0];
      if (!file) return;
      setBusy("upload");
      const fd = new FormData();
      fd.append("file", file);
      const token = await getAdminToken();
      const res = await fetch(`${getBackendUrl()}/api/admin/grocery/upload-image`, {
        method: "POST", headers: { Authorization: `Bearer ${token}` }, body: fd,
      });
      const data = await res.json();
      if (data?.image_url) setEdit(prev => prev ? { ...prev, image_url: data.image_url } : prev);
      setBusy("");
    };
    input.click();
  };

  const downloadTemplate = async () => {
    if (Platform.OS !== "web") return;
    setBusy("template");
    try {
      const token = await getAdminToken();
      const res = await fetch(`${getBackendUrl()}/api/admin/grocery/template`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Download failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "BongConnekt_Product_Catalogue_Template.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      window.alert("Could not download the template. Please try again.");
    }
    setBusy("");
  };

  const uploadTemplate = async () => {
    if (Platform.OS !== "web") return;
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
    input.onchange = async (e: any) => {
      const f = e.target.files?.[0];
      if (!f) return;
      setBusy("upload-template");
      try {
        const fd = new FormData();
        fd.append("file", f);
        const token = await getAdminToken();
        const res = await fetch(`${getBackendUrl()}/api/admin/grocery/upload-template`, {
          method: "POST", headers: { Authorization: `Bearer ${token}` }, body: fd,
        });
        const data = await res.json();
        if (res.ok) {
          const errs = Array.isArray(data.errors) ? data.errors : [];
          setImportErrors(errs);
          let msg = `Import complete — ${data.inserted} new, ${data.updated} updated (${data.products} products).`;
          if (errs.length) msg += `\n\n${errs.length} row(s) were skipped due to invalid data — see the list below.`;
          else msg += " Add photos from each item next.";
          window.alert(msg);
          await load(1);
        } else {
          window.alert(data?.detail || "Upload failed. Please check the file and try again.");
        }
      } catch {
        window.alert("Upload failed. Please try again.");
      }
      setBusy("");
    };
    input.click();
  };

  const imgSrc = (u: string) => (/^https?:/i.test(u) ? u : `${getBackendUrl()}${u}`);

  return (
    <AdminShell title="Grocery Catalog">
      <View style={styles.actionRow}>
        <Text style={styles.count}>{total.toLocaleString()} items</Text>
        <View style={{ flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" }}>
          <TouchableOpacity testID="grocery-download-template" style={[styles.ghostBtn, busy === "template" && { opacity: 0.6 }]} onPress={downloadTemplate} disabled={!!busy}>
            {busy === "template" ? <ActivityIndicator size="small" color={colors.primary} /> : <Ionicons name="document-text-outline" size={16} color={colors.text} />}
            <Text style={styles.ghostBtnText}>Download template</Text>
          </TouchableOpacity>
          <TouchableOpacity testID="grocery-upload-template" style={[styles.ghostBtn, busy === "upload-template" && { opacity: 0.6 }]} onPress={uploadTemplate} disabled={!!busy}>
            {busy === "upload-template" ? <ActivityIndicator size="small" color={colors.primary} /> : <Ionicons name="cloud-upload-outline" size={16} color={colors.text} />}
            <Text style={styles.ghostBtnText}>Upload template</Text>
          </TouchableOpacity>
          <TouchableOpacity testID="grocery-bulk-toggle" style={[styles.ghostBtn, selectMode && { borderColor: colors.primary, backgroundColor: colors.surfaceAlt }]} onPress={() => (selectMode ? exitSelectMode() : setSelectMode(true))}>
            <Ionicons name={selectMode ? "close" : "swap-horizontal"} size={16} color={selectMode ? colors.primary : colors.text} />
            <Text style={[styles.ghostBtnText, selectMode && { color: colors.primary }]}>{selectMode ? "Exit select" : "Bulk move"}</Text>
          </TouchableOpacity>
          <TouchableOpacity testID="new-grocery-btn" style={styles.primaryBtn} onPress={() => openEdit(null)}>
            <Ionicons name="add" size={16} color="#fff" />
            <Text style={styles.primaryBtnText}>New item</Text>
          </TouchableOpacity>
        </View>
      </View>

      {importErrors.length > 0 && (
        <View style={styles.importErrBox} testID="import-errors">
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <Ionicons name="warning" size={16} color={colors.danger} />
            <Text style={styles.importErrTitle}>{importErrors.length} row(s) skipped on last import</Text>
            <View style={{ flex: 1 }} />
            <TouchableOpacity testID="import-errors-dismiss" onPress={() => setImportErrors([])}>
              <Ionicons name="close" size={16} color={colors.textMuted} />
            </TouchableOpacity>
          </View>
          {importErrors.slice(0, 20).map((e, i) => (
            <Text key={i} style={styles.importErrRow}>Row {e.row}: {e.reason}</Text>
          ))}
          {importErrors.length > 20 && <Text style={styles.importErrRow}>…and {importErrors.length - 20} more</Text>}
        </View>
      )}

      <View style={styles.filters}>
        <View style={styles.searchBar}>
          <Ionicons name="search" size={16} color={colors.textMuted} />
          <TextInput
            testID="grocery-admin-search"
            value={q} onChangeText={setQ}
            onSubmitEditing={() => setQuery(q.trim())} returnKeyType="search"
            placeholder="Search items…" placeholderTextColor={colors.textMuted}
            style={styles.searchInput}
          />
        </View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6, alignItems: "center" }}>
          {["All", ...cats].map(c => (
            <TouchableOpacity key={c} onPress={() => setCat(c)} style={[styles.chip, cat === c && styles.chipActive]}>
              <Text style={[styles.chipText, cat === c && { color: "#fff" }]} numberOfLines={1}>{c}</Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      </View>

      {selectMode && (
        <View style={styles.bulkBar} testID="grocery-bulk-bar">
          <Text style={styles.bulkCount}>{selected.size} selected</Text>
          <TouchableOpacity onPress={selectAllOnPage} style={styles.bulkGhost}><Text style={styles.bulkGhostText}>Select all on page</Text></TouchableOpacity>
          {selected.size > 0 && <TouchableOpacity onPress={clearSelection} style={styles.bulkGhost}><Text style={styles.bulkGhostText}>Clear</Text></TouchableOpacity>}
          <View style={styles.bulkSpacer} />
          <View style={styles.bulkPicker}>
            <TouchableOpacity testID="grocery-bulk-target" style={styles.selectBox} onPress={() => setMovePickerOpen(o => !o)} activeOpacity={0.8}>
              <Text style={styles.selectText} numberOfLines={1}>{moveTarget || "Move to category…"}</Text>
              <Ionicons name={movePickerOpen ? "chevron-up" : "chevron-down"} size={18} color={colors.textMuted} />
            </TouchableOpacity>
            {movePickerOpen && (
              <View style={styles.bulkDropdown}>
                <ScrollView style={{ maxHeight: 260 }} nestedScrollEnabled keyboardShouldPersistTaps="handled">
                  {CATEGORIES.map(c => (
                    <TouchableOpacity key={c} testID={`bulk-cat-${c}`} style={[styles.dropdownItem, c === moveTarget && styles.dropdownItemOn]} onPress={() => { setMoveTarget(c); setMovePickerOpen(false); }}>
                      <Text style={[styles.dropdownItemText, c === moveTarget && { color: colors.primary, fontWeight: "800" }]}>{c}</Text>
                      {c === moveTarget && <Ionicons name="checkmark" size={16} color={colors.primary} />}
                    </TouchableOpacity>
                  ))}
                </ScrollView>
              </View>
            )}
          </View>
          <TouchableOpacity testID="grocery-bulk-apply" disabled={!moveTarget || selected.size === 0 || moving} onPress={applyBulkMove} style={[styles.primaryBtn, (!moveTarget || selected.size === 0 || moving) && { opacity: 0.5 }]}>
            {moving ? <ActivityIndicator size="small" color="#fff" /> : <Ionicons name="checkmark" size={16} color="#fff" />}
            <Text style={styles.primaryBtnText}>Move</Text>
          </TouchableOpacity>
        </View>
      )}
      {loading ? <ActivityIndicator color={colors.primary} size="large" style={{ marginTop: 30 }} /> : (
        <>
          <View style={styles.grid}>
            {items.map(g => {
              const sel = selected.has(g.item_id);
              const CardWrap: any = selectMode ? TouchableOpacity : View;
              return (
              <CardWrap key={g.item_id} activeOpacity={0.85} onPress={selectMode ? () => toggleSelect(g.item_id) : undefined} style={[styles.card, selectMode && sel && styles.cardSelected]} testID={`grocery-admin-card-${g.item_id}`}>
                {g.image_url ? <Image source={{ uri: imgSrc(g.image_url) }} style={styles.img} /> : <View style={[styles.img, { alignItems: "center", justifyContent: "center" }]}><Ionicons name="image-outline" size={24} color={colors.textMuted} /></View>}
                {selectMode && (
                  <View style={[styles.selBadge, sel && styles.selBadgeOn]} testID={`grocery-select-${g.item_id}`}>
                    <Ionicons name={sel ? "checkmark" : "ellipse-outline"} size={16} color={sel ? "#fff" : colors.textMuted} />
                  </View>
                )}
                <View style={{ flex: 1, padding: spacing.md, gap: 4 }}>
                  <Text style={styles.name} numberOfLines={2}>{g.title}</Text>
                  <Text style={styles.meta}>{g.category}{g.unit ? ` · ${g.unit}` : ""}</Text>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <Text style={styles.price}>CA${(g.price_cents / 100).toFixed(2)}</Text>
                    {!g.in_stock && <Text style={styles.badgeOff}>OOS</Text>}
                    {g.is_featured && <Text style={styles.badgeFeat}>★</Text>}
                  </View>
                  {!selectMode && (
                    <View style={styles.foot}>
                      <TouchableOpacity testID={`edit-grocery-${g.item_id}`} style={styles.iconBtn} onPress={() => openEdit(g)}><Ionicons name="pencil" size={14} color={colors.text} /></TouchableOpacity>
                      <TouchableOpacity testID={`del-grocery-${g.item_id}`} style={styles.iconBtn} onPress={() => remove(g)}><Ionicons name="trash-outline" size={14} color={colors.danger} /></TouchableOpacity>
                    </View>
                  )}
                </View>
              </CardWrap>
              );
            })}
            {items.length === 0 && <Text style={styles.empty}>No items.</Text>}
          </View>

          {pages > 1 && (
            <View style={styles.pager}>
              <TouchableOpacity disabled={page <= 1} onPress={() => load(page - 1)} style={[styles.pageBtn, page <= 1 && { opacity: 0.4 }]}><Ionicons name="chevron-back" size={16} color={colors.text} /></TouchableOpacity>
              <Text style={styles.pageText}>Page {page} / {pages}</Text>
              <TouchableOpacity disabled={page >= pages} onPress={() => load(page + 1)} style={[styles.pageBtn, page >= pages && { opacity: 0.4 }]}><Ionicons name="chevron-forward" size={16} color={colors.text} /></TouchableOpacity>
            </View>
          )}
        </>
      )}

      <Modal visible={!!edit} transparent animationType="slide" onRequestClose={() => setEdit(null)}>
        <View style={styles.overlay}>
          <View style={styles.modalCard} testID="grocery-edit-modal">
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>{edit?.title ? "Edit item" : "New item"}</Text>
              <TouchableOpacity onPress={() => setEdit(null)}><Ionicons name="close" size={22} color={colors.text} /></TouchableOpacity>
            </View>
            {edit && (
              <ScrollView contentContainerStyle={{ gap: spacing.md, paddingBottom: spacing.lg }} keyboardShouldPersistTaps="handled">
                <Field label="Title" value={edit.title} onChange={t => setEdit({ ...edit, title: t })} testID="grocery-title" />

                <View style={{ flexDirection: "row", gap: spacing.sm, zIndex: 10 }}>
                  <View style={{ flex: 1.4 }}>
                    <Text style={styles.label}>Category</Text>
                    <TouchableOpacity testID="grocery-category" style={styles.selectBox} onPress={() => setCatPickerOpen(o => !o)} activeOpacity={0.8}>
                      <Text style={styles.selectText} numberOfLines={1}>{edit.category || "Select a category"}</Text>
                      <Ionicons name={catPickerOpen ? "chevron-up" : "chevron-down"} size={18} color={colors.textMuted} />
                    </TouchableOpacity>
                    {catPickerOpen && (
                      <View style={styles.dropdown}>
                        <ScrollView style={{ maxHeight: 240 }} nestedScrollEnabled keyboardShouldPersistTaps="handled">
                          {(CATEGORIES.includes(edit.category) ? CATEGORIES : [edit.category, ...CATEGORIES]).map(c => {
                            const on = c === edit.category;
                            return (
                              <TouchableOpacity key={c} testID={`cat-opt-${c}`} style={[styles.dropdownItem, on && styles.dropdownItemOn]} onPress={() => { setEdit({ ...edit, category: c }); setCatPickerOpen(false); }}>
                                <Text style={[styles.dropdownItemText, on && { color: colors.primary, fontWeight: "800" }]}>{c}</Text>
                                {on && <Ionicons name="checkmark" size={16} color={colors.primary} />}
                              </TouchableOpacity>
                            );
                          })}
                        </ScrollView>
                      </View>
                    )}
                  </View>
                  <View style={{ flex: 1 }}><Field label="Unit (e.g. 2 lb)" value={edit.unit} onChange={t => setEdit({ ...edit, unit: t })} /></View>
                </View>

                {/* Subcategory — shown for categories that use them (e.g. Fresh Fish). */}
                {(SUBCATEGORIES[edit.category] || []).length > 0 && (
                  <View style={{ zIndex: 5 }}>
                    <Text style={styles.label}>Subcategory</Text>
                    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
                      {["", ...SUBCATEGORIES[edit.category]].map(sub => {
                        const on = (edit.subcategory || "") === sub;
                        return (
                          <TouchableOpacity
                            key={sub || "none"}
                            testID={`subcat-opt-${sub || "none"}`}
                            style={[styles.subPill, on && styles.subPillOn]}
                            onPress={() => setEdit({ ...edit, subcategory: sub })}
                          >
                            <Text style={[styles.subPillText, on && { color: "#fff" }]}>{sub || "None"}</Text>
                          </TouchableOpacity>
                        );
                      })}
                    </View>
                  </View>
                )}

                {/* Pricing — hidden when the product has variants (price comes from variants) */}
                {variants.filter(v => v.title.trim()).length === 0 ? (
                  <View style={{ flexDirection: "row", gap: spacing.sm }}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.label}>Price (CAD)</Text>
                      <TextInput testID="grocery-price" value={priceStr} onChangeText={setPriceStr} keyboardType="decimal-pad" style={styles.input} />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.label}>Compare-at (optional)</Text>
                      <TextInput value={compareStr} onChangeText={setCompareStr} keyboardType="decimal-pad" style={styles.input} />
                    </View>
                  </View>
                ) : (
                  <View style={styles.infoNote}>
                    <Ionicons name="pricetags-outline" size={14} color={colors.primary} />
                    <Text style={styles.infoNoteText}>Price is set per variant below — the storefront shows the lowest available price.</Text>
                  </View>
                )}

                {/* Variants editor */}
                <View style={styles.variantsSection}>
                  <View style={styles.variantsHead}>
                    <Text style={styles.sectionHeading}>Variants / options</Text>
                    <Text style={styles.sectionHint}>{variants.filter(v => v.title.trim()).length ? `${variants.filter(v => v.title.trim()).length} option(s)` : "No variants — single price"}</Text>
                  </View>
                  {variants.map((v, i) => (
                    <View key={v.variant_id} style={styles.variantRow} testID={`variant-edit-${i}`}>
                      <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                        <TextInput testID={`variant-title-${i}`} value={v.title} onChangeText={t => patchVariant(i, { title: t })} placeholder="Option name (e.g. 2 lb / With skin)" placeholderTextColor={colors.textMuted} style={[styles.input, { flex: 1 }]} />
                        <TouchableOpacity testID={`variant-remove-${i}`} onPress={() => removeVariant(i)} style={styles.iconBtn}><Ionicons name="trash-outline" size={16} color={colors.danger} /></TouchableOpacity>
                      </View>
                      <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, marginTop: 6 }}>
                        <View style={{ flex: 1 }}>
                          <Text style={styles.miniLabel}>Price</Text>
                          <TextInput testID={`variant-price-${i}`} value={v.priceStr} onChangeText={t => patchVariant(i, { priceStr: t })} keyboardType="decimal-pad" style={styles.input} />
                        </View>
                        <View style={{ flex: 1 }}>
                          <Text style={styles.miniLabel}>Compare-at</Text>
                          <TextInput value={v.compareStr} onChangeText={t => patchVariant(i, { compareStr: t })} keyboardType="decimal-pad" style={styles.input} />
                        </View>
                        <TouchableOpacity testID={`variant-avail-${i}`} onPress={() => patchVariant(i, { available: !v.available })} style={[styles.availPill, v.available ? styles.availOn : styles.availOff]}>
                          <Ionicons name={v.available ? "checkmark-circle" : "close-circle"} size={15} color={v.available ? colors.success : colors.danger} />
                          <Text style={[styles.availText, { color: v.available ? colors.success : colors.danger }]}>{v.available ? "In stock" : "Sold out"}</Text>
                        </TouchableOpacity>
                      </View>
                    </View>
                  ))}
                  <TouchableOpacity testID="variant-add" onPress={addVariant} style={styles.addVariantBtn}>
                    <Ionicons name="add-circle-outline" size={18} color={colors.primary} />
                    <Text style={styles.addVariantText}>Add variant</Text>
                  </TouchableOpacity>
                </View>

                <View>
                  <Text style={styles.label}>Image</Text>
                  <View style={{ flexDirection: "row", gap: spacing.sm, alignItems: "center" }}>
                    {edit.image_url ? <Image source={{ uri: imgSrc(edit.image_url) }} style={styles.previewImg} /> : <View style={[styles.previewImg, { alignItems: "center", justifyContent: "center" }]}><Ionicons name="image-outline" size={22} color={colors.textMuted} /></View>}
                    <View style={{ flex: 1, gap: 6 }}>
                      <TextInput value={edit.image_url} onChangeText={t => setEdit({ ...edit, image_url: t })} placeholder="Image URL" placeholderTextColor={colors.textMuted} style={styles.input} />
                      {Platform.OS === "web" && (
                        <TouchableOpacity testID="grocery-upload-image" style={styles.smallBtn} onPress={pickImage} disabled={busy === "upload"}>
                          {busy === "upload" ? <ActivityIndicator size="small" color="#fff" /> : <Ionicons name="cloud-upload-outline" size={14} color="#fff" />}
                          <Text style={styles.smallBtnText}>Upload photo</Text>
                        </TouchableOpacity>
                      )}
                    </View>
                  </View>
                </View>
                <Field label="Description" value={edit.description} onChange={t => setEdit({ ...edit, description: t })} multiline />
                <View style={{ flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" }}>
                  <Toggle label="In stock" value={edit.in_stock} onToggle={() => setEdit({ ...edit, in_stock: !edit.in_stock })} />
                  <Toggle label="Featured" value={edit.is_featured} onToggle={() => setEdit({ ...edit, is_featured: !edit.is_featured })} />
                  <Toggle label="Active" value={edit.is_active} onToggle={() => setEdit({ ...edit, is_active: !edit.is_active })} />
                </View>
                <TouchableOpacity testID="grocery-save" style={styles.saveBtn} onPress={save}>
                  <Ionicons name="save" size={16} color="#fff" />
                  <Text style={styles.primaryBtnText}>Save item</Text>
                </TouchableOpacity>
              </ScrollView>
            )}
          </View>
        </View>
      </Modal>
      <Modal visible={!!confirmDel} transparent animationType="fade" onRequestClose={() => setConfirmDel(null)}>
        <View style={styles.overlay}>
          <View style={styles.confirmCard} testID="grocery-delete-confirm">
            <View style={styles.confirmIcon}><Ionicons name="trash" size={24} color={colors.danger} /></View>
            <Text style={styles.confirmTitle}>Delete item?</Text>
            <Text style={styles.confirmBody} numberOfLines={3}>
              &quot;{confirmDel?.title}&quot; will be removed from the store. You can re-add it later.
            </Text>
            <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.md }}>
              <TouchableOpacity testID="grocery-delete-cancel" style={[styles.confirmBtn, styles.confirmCancel]} onPress={() => setConfirmDel(null)} disabled={deleting}>
                <Text style={[styles.confirmBtnText, { color: colors.text }]}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity testID="grocery-delete-ok" style={[styles.confirmBtn, styles.confirmDelete]} onPress={doDelete} disabled={deleting}>
                {deleting ? <ActivityIndicator size="small" color="#fff" /> : <Text style={styles.confirmBtnText}>Delete</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </AdminShell>
  );
}

function Field({ label, value, onChange, multiline, testID }: any) {
  return (
    <View>
      <Text style={styles.label}>{label}</Text>
      <TextInput testID={testID} value={value} onChangeText={onChange} multiline={multiline} style={[styles.input, multiline && { minHeight: 80 }]} />
    </View>
  );
}
function Toggle({ label, value, onToggle }: { label: string; value: boolean; onToggle: () => void }) {
  return (
    <TouchableOpacity onPress={onToggle} style={[styles.pill, value && styles.pillActive]}>
      <Ionicons name={value ? "checkmark-circle" : "ellipse-outline"} size={16} color={value ? "#fff" : colors.text} />
      <Text style={[styles.pillText, value && { color: "#fff" }]}>{label}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  actionRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: spacing.sm },
  count: { color: colors.textMuted, fontWeight: "700" },
  primaryBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.primary, paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.pill, ...shadows.soft },
  primaryBtnText: { color: "#fff", fontWeight: "800", fontSize: 14 },
  ghostBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 14, paddingVertical: 10, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  ghostBtnText: { color: colors.text, fontWeight: "700", fontSize: 13 },
  smallBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4, backgroundColor: colors.primary, paddingHorizontal: 10, paddingVertical: 8, borderRadius: radius.pill },
  smallBtnText: { color: "#fff", fontSize: 12, fontWeight: "700" },

  filters: { gap: spacing.sm, marginTop: spacing.md },
  searchBar: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radius.pill, paddingHorizontal: spacing.md, height: 42, maxWidth: 380 },
  searchInput: { flex: 1, color: colors.text, fontSize: 14 },
  chip: { height: 34, flexShrink: 0, paddingHorizontal: 12, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center" },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { fontSize: 12, fontWeight: "700", color: colors.text },

  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, marginTop: spacing.md },
  card: { flexGrow: 1, flexBasis: 220, minWidth: 220, maxWidth: 320, backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, overflow: "hidden", ...shadows.soft },
  cardSelected: { borderColor: colors.primary, borderWidth: 2 },
  selBadge: { position: "absolute", top: 8, left: 8, width: 28, height: 28, borderRadius: 14, backgroundColor: "rgba(255,255,255,0.9)", borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  selBadgeOn: { backgroundColor: colors.primary, borderColor: colors.primary },

  // Bulk recategorize toolbar
  bulkBar: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: spacing.sm, marginTop: spacing.md, padding: spacing.md, backgroundColor: colors.surfaceAlt, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, zIndex: 50 },
  bulkCount: { fontWeight: "800", color: colors.text, fontSize: 14 },
  bulkGhost: { paddingHorizontal: 10, paddingVertical: 8, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  bulkGhostText: { fontSize: 12, fontWeight: "700", color: colors.text },
  bulkSpacer: { flexGrow: 1, minWidth: 4 },
  bulkPicker: { minWidth: 210, zIndex: 60 },
  bulkDropdown: { position: "absolute", top: 50, left: 0, right: 0, zIndex: 70, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, overflow: "hidden", ...shadows.card },
  img: { width: "100%", height: 130, backgroundColor: colors.surfaceAlt },
  name: { fontSize: 13, fontWeight: "800", color: colors.text, minHeight: 34 },
  meta: { fontSize: 11, color: colors.textMuted },
  price: { color: colors.primary, fontWeight: "800", fontSize: 14 },
  badgeOff: { fontSize: 9, fontWeight: "900", color: colors.danger, borderWidth: 1, borderColor: colors.danger, paddingHorizontal: 4, borderRadius: 4 },
  badgeFeat: { fontSize: 12, color: colors.secondary, fontWeight: "900" },
  foot: { flexDirection: "row", gap: 6, marginTop: 4 },
  iconBtn: { width: 30, height: 30, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  empty: { color: colors.textMuted, padding: spacing.xl, width: "100%", textAlign: "center" },
  pager: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.md, marginTop: spacing.lg },
  pageBtn: { width: 38, height: 38, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  pageText: { color: colors.text, fontWeight: "700" },

  overlay: { flex: 1, backgroundColor: colors.overlay, alignItems: "center", justifyContent: "center", padding: spacing.lg },
  modalCard: { width: "100%", maxWidth: 640, maxHeight: "92%", backgroundColor: colors.surface, borderRadius: radius.xl, padding: spacing.lg, gap: spacing.sm, ...shadows.card },
  modalHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.sm },
  modalTitle: { fontSize: 20, fontWeight: "800", color: colors.text },
  label: { color: colors.textMuted, letterSpacing: 2, fontSize: 10, fontWeight: "800", marginBottom: 4 },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: 10, color: colors.text, fontSize: 14 },
  previewImg: { width: 84, height: 84, borderRadius: radius.md, backgroundColor: colors.surfaceAlt },
  pill: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  pillActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  pillText: { fontSize: 12, color: colors.text, fontWeight: "700" },
  saveBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.primary, paddingVertical: 14, borderRadius: radius.pill, marginTop: spacing.sm },

  // Category dropdown
  selectBox: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: 12 },
  selectText: { flex: 1, color: colors.text, fontSize: 14, fontWeight: "600" },
  dropdown: { marginTop: 4, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, overflow: "hidden", ...shadows.card },
  dropdownItem: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.md, paddingVertical: 11, borderBottomWidth: 1, borderBottomColor: colors.border },
  dropdownItemOn: { backgroundColor: colors.surfaceAlt },
  dropdownItemText: { color: colors.text, fontSize: 14, fontWeight: "600" },

  // Variants editor
  infoNote: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.surfaceAlt, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border },
  infoNoteText: { flex: 1, color: colors.textMuted, fontSize: 12, fontWeight: "600" },
  variantsSection: { backgroundColor: colors.surfaceAlt, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, gap: spacing.sm },
  variantsHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  sectionHeading: { fontSize: 13, fontWeight: "800", color: colors.text },
  sectionHint: { fontSize: 11, color: colors.textMuted, fontWeight: "700" },
  variantRow: { backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.sm },
  miniLabel: { color: colors.textMuted, fontSize: 9, fontWeight: "800", letterSpacing: 1, marginBottom: 3 },
  availPill: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 10, borderRadius: radius.md, borderWidth: 1, alignSelf: "flex-end" },
  availOn: { backgroundColor: "#DCFCE7", borderColor: "#BBF7D0" },
  availOff: { backgroundColor: "#FEE2E2", borderColor: "#FECACA" },
  availText: { fontSize: 11, fontWeight: "800" },
  addVariantBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 10, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.primary, borderStyle: "dashed" },
  addVariantText: { color: colors.primary, fontWeight: "800", fontSize: 13 },

  // Import error banner
  importErrBox: { marginTop: spacing.md, backgroundColor: "#FEF2F2", borderWidth: 1, borderColor: "#FECACA", borderRadius: radius.md, padding: spacing.md, gap: 4 },
  importErrTitle: { fontSize: 13, fontWeight: "800", color: colors.danger },
  subPill: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.pill, borderWidth: 1.5, borderColor: colors.border, backgroundColor: colors.surface },
  subPillOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  subPillText: { fontSize: 13, fontWeight: "700", color: colors.text },
  importErrRow: { fontSize: 12, color: "#7F1D1D", marginLeft: 22 },

  // Delete confirm modal
  confirmCard: { width: "100%", maxWidth: 380, backgroundColor: colors.surface, borderRadius: radius.xl, padding: spacing.xl, alignItems: "center", gap: 6, ...shadows.card },
  confirmIcon: { width: 52, height: 52, borderRadius: 26, backgroundColor: "#FEE2E2", alignItems: "center", justifyContent: "center", marginBottom: 4 },
  confirmTitle: { fontSize: 18, fontWeight: "800", color: colors.text },
  confirmBody: { fontSize: 13.5, color: colors.textMuted, textAlign: "center", lineHeight: 19 },
  confirmBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", height: 46, borderRadius: radius.pill },
  confirmCancel: { backgroundColor: colors.surfaceAlt, borderWidth: 1, borderColor: colors.border },
  confirmDelete: { backgroundColor: colors.danger },
  confirmBtnText: { color: "#fff", fontWeight: "800", fontSize: 14 },
});
