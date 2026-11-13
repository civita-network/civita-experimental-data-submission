"""Turn a draft of extracted rows into the files a contributor sends back.

Usage:
  python build_output.py DRAFT.json OUT_DIR [--formats json,csv,xlsx] [--allow-dangling]
                         [--correction] [--sent]

DRAFT.json:
  {
    "contributor": {"name": "...", "university": "...", "email": "..."},
    "tables": {
      "literature_sources": [ {"@key": "src1", "title": "...", "year": 2021, ...} ],
      "tests":   [ {"@key": "t1", "source_id": "@src1", "test_type": "...", ...} ],
      "figures": [ {"@key": "fig3a", "source_id": "@src1",
                    "curves": [{"legend": "C30", "points": [[0, 0], [0.001, 12.5]]}], ...} ]
    }
  }

Rules (each enforced; a violation stops the build with a message, nothing is written):
  - only tables and fields from schema/civita_schema.json; every row of a table with an
    ID needs a stable "@key" (the same key always gets the same ID, across re-runs);
  - links to other rows are written "@key"; list links (e.g. linked_test_ids) take a
    list of "@key"s; a row may only link to rows of the same paper;
  - controlled fields must use a value from the allowed list, exactly;
  - IDs are never typed by hand: they are minted from the contributor's email;
  - the checks the database runs after merging (required fields and links, ranges,
    numeric values, duplicate labels, curve physics) are run here first.

One OUT_DIR holds one paper. Its digitize_state.json (contributor, dataset namespace,
counters, key->ID map, the paper's DOI/title, record fingerprints) keeps IDs stable when
the same paper is rebuilt. Keep that file with the dataset; never delete it.

--correction  allow the paper's title/DOI to change (fixing a typo in them).
--sent        record this build as the version sent to the coordinator; later builds
              report records changed or removed since then, and write the new records
              alone to concrete_database_additions.json.
"""
import argparse
import csv
import decimal
import hashlib
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import civita_ids  # noqa: E402

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "schema", "civita_schema.json")
CONTRIB_FIELDS = ("contributor_university", "contributor_name", "contributor_email")
STATE_NAME = "digitize_state.json"
# characters Excel/XML cannot store; they come from PDF text (form feeds, etc.)
CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class BuildError(Exception):
    pass


def load_schema():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def js_number(v):
    """A float printed the way JavaScript's String(number) prints it."""
    if v == 0:
        return "0"
    r = repr(float(v))
    if 1e-6 <= abs(v) < 1e21:
        s = format(decimal.Decimal(r), "f")
        return s.rstrip("0").rstrip(".") if "." in s else s
    m, _, e = ("%r" % float(v)).partition("e")
    m = m.rstrip("0").rstrip(".") if "." in m else m
    return "%se%s%d" % (m, "-" if int(e) < 0 else "+", abs(int(e)))


def to_str(v, where):
    """CIVITA stores every cell as a string ('' for blank); numbers print like JavaScript."""
    if v is None:
        return ""
    if isinstance(v, bool):
        raise BuildError("%s: true/false is not a valid cell; use the allowed yes/no value" % where)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise BuildError("%s: non-finite number %r" % (where, v))
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return js_number(v)
    if isinstance(v, str):
        m = CTRL_RE.search(v)
        if m:
            raise BuildError("%s: contains the invisible control character %r (usually copied from PDF "
                             "text); remove it" % (where, m.group(0)))
        return v
    raise BuildError("%s: value must be text or a number, got %s" % (where, type(v).__name__))


def norm_title(t):
    return re.sub(r"[^a-z0-9]+", " ", str(t or "").lower()).strip()


def norm_doi(d):
    d = str(d or "").strip().lower()
    return re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", d)


def load_state(out_dir, contributor):
    path = os.path.join(out_dir, STATE_NAME)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                st = json.load(f)
            for k in ("contributor", "namespace", "counters", "keys", "fingerprints"):
                if k not in st:
                    raise KeyError(k)
            old_email = st["contributor"]["email"]
        except (ValueError, KeyError, TypeError) as e:
            raise BuildError("%s is damaged (%s). Do NOT delete it: it holds the record IDs of files you may "
                             "already have sent. Restore it from a backup or from the copy you sent, or ask the "
                             "database coordinator what to do." % (path, e))
        if civita_ids.norm_email(old_email) != civita_ids.norm_email(contributor["email"]):
            raise BuildError("this dataset folder belongs to %s; the draft says %s. Use a new OUT_DIR."
                             % (old_email, contributor["email"]))
        st.setdefault("sources", {})
        st.setdefault("baseline", {})
        return st, path
    st = {"contributor": dict(contributor, prefix=civita_ids.derive_prefix(contributor["email"])),
          "namespace": civita_ids.new_namespace(), "counters": {}, "keys": {}, "fingerprints": {},
          "sources": {}, "baseline": {}}
    return st, path


def check_contributor(c):
    if not isinstance(c, dict):
        raise BuildError("draft needs a 'contributor' object with name, university, email")
    for k in ("name", "university", "email"):
        v = c.get(k)
        if not isinstance(v, str) or not v.strip():
            raise BuildError("contributor.%s is missing (it must be text)" % k)
    if not civita_ids.valid_email(c["email"]):
        raise BuildError("contributor.email %r is not a valid email address" % c["email"])


def mint(state, table, key, prefix):
    ref = table + "/" + key
    if ref in state["keys"]:
        return state["keys"][ref]
    n = state["counters"].get(prefix, 0) + 1
    new_id = civita_ids.make_id(state["contributor"]["prefix"], state["namespace"], prefix, n)
    state["counters"][prefix] = n
    state["keys"][ref] = new_id
    return new_id


DIGITIZER_DIAG = {"kind", "pieces", "dropped_short_pieces", "markers_stripped", "piece_starts"}
HEX_RE = re.compile(r"^\s*#?[0-9a-fA-F]{6}\s*$")


def curves_to_json(curves, where, warnings):
    if isinstance(curves, str):
        try:
            curves = json.loads(curves)
        except ValueError as e:
            raise BuildError("%s: curve_data is not valid JSON (%s); give 'curves' as a list instead" % (where, e))
    if not isinstance(curves, list) or not curves:
        raise BuildError("%s: 'curves' must be a non-empty list" % where)
    out = []
    for ci, c in enumerate(curves):
        w = "%s curve %d" % (where, ci + 1)
        if not isinstance(c, dict):
            raise BuildError("%s: each curve must be an object with 'legend' and 'points'" % w)
        pts = c.get("points")
        if not isinstance(pts, list) or not pts:
            raise BuildError("%s: needs a non-empty 'points' list" % w)
        P = []
        for pi, p in enumerate(pts):
            try:
                if isinstance(p, dict):
                    x, y = p["x"], p["y"]
                else:
                    if not isinstance(p, (list, tuple)) or len(p) < 2:
                        raise ValueError("needs [x, y]")
                    x, y = p[0], p[1]
                if isinstance(x, bool) or isinstance(y, bool):
                    raise ValueError("true/false is not a number")
                x, y = float(x), float(y)
            except (KeyError, ValueError, TypeError) as e:
                raise BuildError("%s point %d: %r is not a point [x, y] of two numbers (%s)" % (w, pi + 1, p, e))
            if not (math.isfinite(x) and math.isfinite(y)):
                raise BuildError("%s point %d: non-finite point (%r, %r)" % (w, pi + 1, x, y))
            P.append({"x": x, "y": y})
        ordering = c.get("ordering", "xy")
        if ordering not in ("xy", "path"):
            raise BuildError("%s: ordering must be 'xy' (one y per x; points get sorted by x, as the database "
                             "does) or 'path' (loops, unloading: kept in drawing order)" % w)
        if ordering == "xy":
            P.sort(key=lambda q: q["x"])
        legend = c.get("legend")
        legend = "Curve %d" % (ci + 1) if legend in (None, "") else to_str(legend, w + ".legend")
        if HEX_RE.match(legend) or legend.lower() in ("black", "red", "blue", "green", "gray", "grey"):
            warnings.append("%s: legend %r is a colour, not the legend printed in the figure; map it" % (w, legend))
        cur = {"legend": legend, "points": P, "ordering": ordering}
        for opt in ("color", "extraction_method"):
            if c.get(opt) not in (None, ""):
                cur[opt] = to_str(c[opt], w + "." + opt)
        # diagnostics digitize_plot.py writes on each curve: accepted, not stored
        extra = set(c) - {"legend", "points", "ordering", "color", "extraction_method"} - DIGITIZER_DIAG
        if extra:
            raise BuildError("%s: unknown curve field(s) %s" % (w, ", ".join(sorted(extra))))
        out.append(cur)
    return out


def build(draft, out_dir, allow_dangling=False, correction=False):
    schema = load_schema()
    tables, vocabs, fkmap = schema["tables"], schema["vocabs"], schema["foreign_keys"]
    if not isinstance(draft, dict):
        raise BuildError("the draft must be a JSON object with 'contributor' and 'tables'")
    check_contributor(draft.get("contributor"))
    contributor = draft["contributor"]
    state, state_path = load_state(out_dir, contributor)
    dtables = draft.get("tables") or {}
    if not isinstance(dtables, dict) or not dtables:
        raise BuildError("draft.tables is empty: nothing to build")
    unknown = sorted(set(dtables) - set(tables))
    if unknown:
        raise BuildError("unknown table(s): %s. Allowed: %s" % (", ".join(unknown), ", ".join(tables)))
    bad = [tn for tn, rows in dtables.items() if not isinstance(rows, list)]
    if bad:
        raise BuildError("table(s) %s must be a list of rows" % ", ".join(bad))

    errors, warnings = [], []
    keysets = {tn: {r["@key"] for r in rows if isinstance(r, dict) and isinstance(r.get("@key"), str)}
               for tn, rows in dtables.items()}
    # Pass 1: mint IDs for every keyed row so links can point forward or backward.
    for tn, rows in dtables.items():
        prefix = tables[tn]["prefix"]
        seen = set()
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append("%s row %d is not an object" % (tn, i + 1))
                continue
            if not prefix:
                continue
            key = row.get("@key")
            if not isinstance(key, str) or not key.strip():
                errors.append("%s row %d needs a stable \"@key\" (e.g. \"%s1\")" % (tn, i + 1, tn[:3]))
                continue
            if key in seen:
                errors.append("%s: @key %r used twice" % (tn, key))
            seen.add(key)
            mint(state, tn, key, prefix)

    # One folder = one paper: a reused folder would give a different paper this paper's IDs,
    # and the database would refuse (or overwrite) the earlier paper's records.
    srows = [r for r in dtables.get("literature_sources", []) if isinstance(r, dict) and isinstance(r.get("@key"), str)]
    idents = {r["@key"]: {"doi": norm_doi(r.get("doi")), "title": norm_title(r.get("title"))} for r in srows}
    for k, idt in idents.items():
        old = state["sources"].get(k)
        if old and not correction and ((old["doi"] and idt["doi"] and old["doi"] != idt["doi"])
                                       or (old["title"] and idt["title"] and old["title"] != idt["title"])):
            errors.append("literature_sources @%s: this folder was built for the paper %r (DOI %s); the draft "
                          "now says %r (DOI %s). Use a NEW output folder for a different paper. If this is the "
                          "same paper and you are fixing its title/DOI, rerun with --correction."
                          % (k, old["title"], old["doi"] or "none", idt["title"], idt["doi"] or "none"))
    if state["sources"] and idents and not correction and not set(idents) & set(state["sources"]):
        errors.append("this folder holds a different paper (%s); use a new output folder for each paper"
                      % ", ".join(repr(v["title"]) for v in state["sources"].values()))

    def resolve(ref_table, val, where):
        if isinstance(val, str) and val.startswith("@"):
            ref = ref_table + "/" + val[1:]
            if ref in state["keys"] and val[1:] in keysets.get(ref_table, set()):
                return state["keys"][ref]
            errors.append("%s: link %s points to no %s row with that @key" % (where, val, ref_table))
            return ""
        s = to_str(val, where)
        if s:
            msg = "%s: %r is not an @key link; links to rows outside this dataset cannot be checked" % (where, s)
            (warnings if allow_dangling else errors).append(msg)
        return s

    db = {tn: [] for tn in tables}
    labels, shared, accepted = {}, {}, {}
    for tn, rows in dtables.items():
        spec = tables[tn]
        fields = [f["name"] for f in spec["fields"]]
        ftype = {f["name"]: f for f in spec["fields"]}
        edges = {e["field"]: e for e in fkmap.get(tn, [])}
        draft_only = {"@key"} | ({"curves", "@accept_physics"} if tn == "figures" else set()) \
            | ({"@label"} if tn == "specimens" else set())
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            where = "%s row %d (%s)" % (tn, i + 1, row.get("@key", "no key"))
            try:
                extra = set(row) - set(fields) - draft_only
                if extra:
                    errors.append("%s: unknown field(s) %s" % (where, ", ".join(sorted(map(str, extra)))))
                if spec["id"] in row and spec["prefix"]:
                    errors.append("%s: do not set %s by hand; it is minted from @key" % (where, spec["id"]))
                out = {}
                for fn in fields:
                    if fn == spec["id"] and spec["prefix"]:
                        out[fn] = state["keys"].get(tn + "/" + str(row.get("@key")), "")
                        continue
                    if tn == "literature_sources" and fn in CONTRIB_FIELDS:
                        want = contributor[fn.replace("contributor_", "")]
                        if fn in row and str(row[fn]) != str(want):
                            errors.append("%s: %s comes from the contributor profile; remove it" % (where, fn))
                        out[fn] = to_str(want, where + "." + fn).strip()
                        continue
                    val = row.get(fn)
                    if fn in edges:
                        e = edges[fn]
                        if e["list"]:
                            items = val if isinstance(val, list) else ([] if val in (None, "") else [val])
                            ids = [x for x in (resolve(e["ref"], v, where + "." + fn) for v in items) if x]
                            if len(set(ids)) < len(ids):
                                warnings.append("%s.%s: the same link is listed twice; kept once" % (where, fn))
                                ids = list(dict.fromkeys(ids))
                            out[fn] = ", ".join(ids)
                        else:
                            out[fn] = "" if val in (None, "") else resolve(e["ref"], val, where + "." + fn)
                        continue
                    if isinstance(val, (list, dict)) and not (tn == "figures" and fn == "curve_data"):
                        errors.append("%s.%s: a list is only allowed for list links" % (where, fn))
                        continue
                    if tn == "figures" and fn == "curve_data":
                        continue  # handled below with 'curves'
                    s = to_str(val, where + "." + fn)
                    if tn == "keywords" and fn == "keyword":
                        s = s.strip()
                    f = ftype[fn]
                    if f.get("type") == "vocab" and s != "":
                        allowed = vocabs.get(f.get("vocab"))
                        if allowed is not None and s not in allowed:
                            near = [a for a in allowed if a.lower() == s.lower().strip()]
                            hint = (" Did you mean %r?" % near[0]) if near else (" Allowed: %s" % ", ".join(allowed))
                            errors.append("%s.%s: %r is not an allowed value.%s" % (where, fn, s, hint))
                    out[fn] = s
                if tn == "figures":
                    figure_row(row, out, where, errors, warnings, accepted)
                if tn == "specimens" and row.get("@label") not in (None, ""):
                    # same convention as the database's own AI import: the paper's specimen label
                    # leads the notes as "[label] ", since specimens have no label column
                    lab = to_str(row["@label"], where + ".@label").strip()
                    if "]" in lab or not lab:
                        errors.append("%s: @label %r cannot contain ']'" % (where, lab))
                    pre = "[" + lab + "]"
                    notes = out.get("notes", "")
                    out["notes"] = notes if notes.startswith(pre) else (pre + " " + notes).strip()
                    labels[out[spec["id"]]] = lab
                if tn in ("material_models", "model_parameters"):
                    if out.get("review_status") not in ("", "unreviewed"):
                        errors.append("%s: review_status is set by the database coordinator; leave it out" % where)
                    out["review_status"] = "unreviewed"
                if tn in ("geometries", "reinforcement_materials"):
                    # the database's AI import merges identical entities within one paper
                    sig = json.dumps({k: v for k, v in out.items() if k != spec["id"]}, sort_keys=True)
                    prev = shared.setdefault(tn, {}).get(sig)
                    if prev:
                        errors.append("%s is identical to %s row @%s: delete it and point to @%s instead"
                                      % (where, tn, prev, prev))
                    else:
                        shared[tn][sig] = row.get("@key")
                db[tn].append(out)
            except BuildError as ex:
                errors.append(str(ex))

    t2s = {r.get("test_id"): r.get("specimen_id") for r in db.get("tests", [])}
    for r in db.get("data", []):
        lab = labels.get(t2s.get(r.get("test_id")))
        if lab and not r.get("specimen_label"):
            r["specimen_label"] = lab

    # keywords: composite key, no duplicates of (source_id, keyword)
    kw = set()
    for r in db.get("keywords", []):
        k = (r.get("source_id"), r.get("keyword", "").lower())
        if not r.get("source_id") or not r.get("keyword", ""):
            errors.append("keywords: every row needs source_id and keyword")
        if k in kw:
            errors.append("keywords: duplicate keyword %r for one source" % r.get("keyword"))
        kw.add(k)

    errors.extend(link_checks(db, tables, fkmap))
    red_errors, red_warnings = database_red_checks(db)
    errors.extend(red_errors)
    warnings.extend(red_warnings)
    for fig in db.get("figures", []):
        fails, warns = physics_checks(fig, db)
        reason = accepted.get(fig.get("figure_id"))
        if fails and reason:
            fig["notes"] = (fig.get("notes", "") + " PHYSICS-ACCEPTED by contributor: " + reason).strip()
            warnings.extend("figures %s: %s (accepted: %s; the database will still mark it red for the "
                            "coordinator to review)" % (fig.get("figure_id"), m, reason) for m in fails)
        else:
            errors.extend("figures %s (%s): %s. Check the overlay, units and axis bounds. If the curve is "
                          "right as printed, set \"@accept_physics\": \"<why>\" on the figure"
                          % (fig.get("figure_id"), fig.get("figure_id_in_paper", ""), m) for m in fails)
        warnings.extend("figures %s: %s" % (fig.get("figure_id"), m) for m in warns)

    if errors:
        raise BuildError("Build stopped, nothing written. Fix these %d problem(s):\n  - " % len(errors)
                         + "\n  - ".join(errors))

    for k, idt in idents.items():
        state["sources"][k] = idt
    # Changed-record report: CIVITA refuses a merge when an ID it already has arrives with
    # different content. Compared against the sent (or first-built) version of each record,
    # so the report repeats on every build until --sent records a new sent version.
    changed, current = [], {}
    for tn, rows in db.items():
        if not tables[tn]["prefix"]:
            continue
        pk = tables[tn]["id"]
        for r in rows:
            fp = hashlib.sha256(json.dumps(r, sort_keys=True).encode("utf-8")).hexdigest()
            current[r[pk]] = (tn, fp)
            old = state["baseline"].get(r[pk])
            if old and old != fp:
                changed.append("%s %s" % (tn, r[pk]))
            state["baseline"].setdefault(r[pk], fp)
    removed = ["%s" % i for i in state["baseline"] if i not in current]
    state["fingerprints"] = {i: fp for i, (tn, fp) in current.items()}
    return db, state, state_path, changed, removed, warnings


def figure_row(row, out, where, errors, warnings, accepted):
    if out.get("plot_type") == "stress_strain":
        # CIVITA's physics check reads strain as mm/mm, or '%' exactly (it converts %).
        xu = out.get("x_units", "").strip().lower()
        if xu not in ("mm/mm", "%", "-", ""):
            errors.append("%s: stress_strain x_units %r. CIVITA expects strain as mm/mm (or '%%'): "
                          "convert the x values (microstrain / 1e6, permille / 1000) and set x_units "
                          "to 'mm/mm'" % (where, out.get("x_units")))
    given = row.get("curves") if "curves" in row else row.get("curve_data")
    if "curves" in row and row.get("curve_data") not in (None, ""):
        errors.append("%s: give either 'curves' or 'curve_data', not both" % where)
    elif given not in (None, "", []):
        cj = curves_to_json(given, where, warnings)
        out["curve_data"] = json.dumps(cj, separators=(",", ":"), ensure_ascii=False)
        out["num_curves"] = str(len(cj))
        if not out.get("legend_entries"):
            # the database splits legend_entries on ", ": keep one entry per curve
            out["legend_entries"] = ", ".join(c["legend"].replace(", ", "; ") for c in cj)
    else:
        out["curve_data"] = ""
    if out.get("review_status") not in ("", "unreviewed"):
        errors.append("%s: review_status is set by the database coordinator; leave it out" % where)
    out["review_status"] = "unreviewed"
    acc = row.get("@accept_physics")
    if acc not in (None, ""):
        if not isinstance(acc, str) or len(acc.strip()) < 10:
            errors.append("%s: @accept_physics must say why the curve is right as printed (a sentence)" % where)
        else:
            accepted[out.get("figure_id")] = to_str(acc.strip(), where + ".@accept_physics")


def write_outputs(db, schema, out_dir, formats, state, state_path, additions):
    """Render every file to *.tmp first (so a failure leaves the previous files untouched),
    then replace: the state file FIRST (IDs in any file on disk are always in the state),
    then the outputs. Files from earlier builds that this build does not produce are removed."""
    tables = schema["tables"]
    plan = []  # (final path, tmp path)

    def tmp_for(p):
        t = p + ".tmp"
        plan.append((p, t))
        return t

    with open(tmp_for(state_path), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    with open(tmp_for(os.path.join(out_dir, "concrete_database.json")), "w", encoding="utf-8") as f:
        json.dump({"db": db}, f, ensure_ascii=False, indent=2)
    add_path = os.path.join(out_dir, "concrete_database_additions.json")
    if additions is not None:
        with open(tmp_for(add_path), "w", encoding="utf-8") as f:
            json.dump({"db": additions}, f, ensure_ascii=False, indent=2)
    used = [t for t in tables if db.get(t)]
    curves = []
    for r in db.get("figures", []):
        if r.get("curve_data"):
            for c in json.loads(r["curve_data"]):
                for i, p in enumerate(c["points"]):
                    curves.append([r["figure_id"], r.get("figure_id_in_paper", ""), c["legend"], i + 1,
                                   js_number(p["x"]), js_number(p["y"])])
    cdir = os.path.join(out_dir, "csv")
    if "csv" in formats:
        os.makedirs(cdir, exist_ok=True)
        for t in used:
            names = [f["name"] for f in tables[t]["fields"]]
            with open(tmp_for(os.path.join(cdir, t + ".csv")), "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(names)
                for r in db[t]:
                    w.writerow([csv_safe(r.get(n, "")) for n in names])
        if curves:
            with open(tmp_for(os.path.join(cdir, "curve_points.csv")), "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["figure_id", "figure_id_in_paper", "legend", "point", "x", "y"])
                w.writerows([[csv_safe(c) for c in row] for row in curves])
    xlsx_path = os.path.join(out_dir, "concrete_database.xlsx")
    if "xlsx" in formats:
        from openpyxl import Workbook
        wb = Workbook()
        wb.remove(wb.active)
        for t in used:
            ws = wb.create_sheet(t[:31])
            names = [f["name"] for f in tables[t]["fields"] if not (t == "figures" and f["name"] == "curve_data")]
            xl_append(ws, names)
            for r in db[t]:
                xl_append(ws, [r.get(n, "") for n in names])
        if curves:
            ws = wb.create_sheet("curve_points")
            xl_append(ws, ["figure_id", "figure_id_in_paper", "legend", "point", "x", "y"])
            for row in curves:
                xl_append(ws, row[:4] + [float(row[4]), float(row[5])])
        wb.save(tmp_for(xlsx_path))

    final = [p for p, _ in plan]
    stale = [xlsx_path, add_path] + ([os.path.join(cdir, n) for n in os.listdir(cdir) if n.endswith(".csv")]
                                     if os.path.isdir(cdir) else [])
    for p, t in plan:
        os.replace(t, p)
    for p in stale:
        if p not in final and os.path.exists(p):
            os.remove(p)
    return [p for p in final if p != state_path]


FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _formula_like(v):
    if not isinstance(v, str) or not v.startswith(FORMULA_START):
        return False
    try:
        float(v)
        return False  # a plain number such as -3.5
    except ValueError:
        return True


def csv_safe(v):
    """Spreadsheet apps run cells starting with = + - @ as formulas; prefix ' to show them as text.
    (The CSV and Excel files are for checking only; concrete_database.json is never altered.)"""
    return "'" + v if _formula_like(v) else v


def xl_append(ws, values):
    ws.append(values)
    for cell in ws[ws.max_row]:
        if isinstance(cell.value, str) and cell.value.startswith("="):
            cell.data_type = "s"  # keep it text, never a formula


# Checks the database marks RED after merging (a red record is sent back to the contributor).
REQUIRED = {"material_batches": ("material_class", "batch_label"), "tests": ("specimen_id",),
            "data": ("data_type",), "extracted_values": ("variable_name", "value", "test_id"),
            "material_models": ("model_name", "model_family"),
            "model_parameters": ("parameter_name", "source_location", "model_id"), "figures": ("caption", "plot_type")}
RANGES = {"material_batches": {"water_binder_ratio": (0.15, 0.95), "cement_content_kg_m3": (80, 900),
                               "max_aggregate_size_mm": (1, 50), "fine_aggregate_content_kg_m3": (0, 1200),
                               "coarse_aggregate_content_kg_m3": (0, 1500)},
          "tests": {"age_days": (0, 3650), "initial_env_temperature_C": (-60, 1300),
                    "initial_env_relative_humidity_percent": (0, 100)},
          "reinforcement_materials": {"yield_strength_mpa": (200, 2000), "rupture_strength_mpa": (250, 2200)},
          "reinforcement_components": {"bar_nominal_diameter_mm": (3, 60), "number_of_reinf_elements": (0, 100)},
          "figures": {"num_curves": (1, 50)}}
# extracted_values whose variable_name contains these words get a plausibility range
NAME_RANGES = (("modulus", 5000, 60000), ("fracture_energy", 10, 1000), ("peak_strain", 0.0001, 0.02))
NUM_RE = re.compile(r"^\s*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")


def leading_number(v):
    """The number the database reads from a cell (it reads a leading number and ignores the rest)."""
    m = NUM_RE.match(str(v))
    return float(m.group(0)) if m else None


def link_checks(db, tables, fkmap):
    """Every row of a table with source_id needs one (the database marks a blank one red), and
    links stay inside one paper: deleting one paper must not orphan another paper's rows."""
    errs = []
    src_of = {}
    for tn, rows in db.items():
        pk = tables[tn]["id"]
        for r in rows:
            if pk and r.get(pk):
                src_of[(tn, r[pk])] = r.get("source_id")
    for tn, edges in fkmap.items():
        for r in db.get(tn, []):
            for e in edges:
                if e["field"] == "source_id":
                    if not r.get("source_id"):
                        errs.append("%s %s: source_id is required (link it to the paper, \"@<source key>\")"
                                    % (tn, _rid(tn, r)))
                    continue
                if not r.get("source_id"):
                    continue
                for v in [x.strip() for x in r.get(e["field"], "").split(",")] if e["list"] else [r.get(e["field"], "")]:
                    other = src_of.get((e["ref"], v))
                    if v and other and other != r["source_id"]:
                        errs.append("%s %s: %s links to a row of a different paper (%s); each paper needs its "
                                    "own rows" % (tn, _rid(tn, r), e["field"], v))
    return errs


def database_red_checks(db):
    errs, warns = [], []
    for tn, fields in REQUIRED.items():
        for r in db.get(tn, []):
            for f in fields:
                if not str(r.get(f, "")).strip():
                    errs.append("%s %s: %s is required" % (tn, _rid(tn, r), f))
    for tn, rng in RANGES.items():
        for r in db.get(tn, []):
            for f, (lo, hi) in rng.items():
                v = str(r.get(f, "")).strip()
                if not v:
                    continue
                x = leading_number(v)
                if x is None or not lo <= x <= hi:
                    errs.append("%s %s: %s = %r must be a number in [%g, %g]" % (tn, _rid(tn, r), f, v, lo, hi))
    for r in db.get("extracted_values", []):
        v = str(r.get("value", "")).strip()
        if not v:
            continue
        x = leading_number(v)
        if x is None:
            errs.append("extracted_values %s: value %r is not a number. Only numbers go in extracted_values; "
                        "put text results (failure mode, crack pattern) in the test's notes" % (r.get("record_id"), v))
            continue
        name = str(r.get("variable_name", "")).lower()
        for word, lo, hi in NAME_RANGES:
            if word in name and not lo <= x <= hi:
                errs.append("extracted_values %s: %s = %g; the database only accepts [%g, %g] for a variable "
                            "named '%s' (MPa for modulus). Check units, or rename the variable if it is not a "
                            "concrete property (e.g. steel modulus)" % (r.get("record_id"), name, x, lo, hi, word))
    for tn, f in (("tests", "test_type"), ("geometries", "specimen_geometry_type")):
        for r in db.get(tn, []):
            if r.get(f) == "other":
                errs.append("%s %s: %s 'other' is marked red by the database. Leave it blank and describe "
                            "it in the notes" % (tn, _rid(tn, r), f))
    for tn, keyf in (("material_batches", lambda r: r.get("batch_label", "")),
                     ("material_models", lambda r: str(r.get("model_name", "")).strip().lower()),
                     ("specimens", lambda r: (re.match(r"^\[([^\]]+)\]", r.get("notes", "")) or [None, ""])[1].strip())):
        seen = {}
        for r in db.get(tn, []):
            k = keyf(r)
            if k and (r.get("source_id"), k) in seen:
                errs.append("%s: %r is used by two records of one source (%s, %s)"
                            % (tn, k, seen[(r.get("source_id"), k)], _rid(tn, r)))
            seen.setdefault((r.get("source_id"), k), _rid(tn, r))
    test_src = {r.get("test_id"): r.get("source_id") for r in db.get("tests", [])}
    for src in db.get("literature_sources", []):
        sid = src.get("source_id")
        if not any(b.get("source_id") == sid for b in db.get("material_batches", [])):
            errs.append("literature_sources %s: needs at least one material_batches row (the database marks a "
                        "source without batches red)" % sid)
        if not any(t.get("source_id") == sid for t in db.get("tests", [])):
            errs.append("literature_sources %s: needs at least one tests row (the database marks a source "
                        "without tests red)" % sid)
        if not any(test_src.get(v.get("test_id")) == sid for v in db.get("extracted_values", [])):
            warns.append("literature_sources %s: no extracted_values (allowed, but flagged for review)" % sid)
        if not norm_doi(src.get("doi")) or len(norm_title(src.get("title"))) < 12:
            warns.append("literature_sources %s: give the DOI and the full title if the paper has them; the "
                         "database uses them to spot the same paper sent twice" % sid)
        # UNCERTAIN, counted the way the database counts it: 3+ on one paper marks it red
        recs = [r for tn in ("material_batches", "tests", "reinforcement_components", "figures")
                for r in db.get(tn, []) if r.get("source_id") == sid]
        recs += [r for tn in ("data", "extracted_values") for r in db.get(tn, []) if test_src.get(r.get("test_id")) == sid]
        unc = [_rid("", r) for r in recs if "UNCERTAIN" in (r.get("notes") or r.get("comments") or "")]
        if len(unc) >= 3:
            warns.append("literature_sources %s: %d records say UNCERTAIN (%s). The database marks a paper with "
                         "3 or more red and flags it for the coordinator to review; that is intended when you "
                         "really are unsure, so tell the user which values they are"
                         % (sid, len(unc), ", ".join(unc[:5]) + (" ..." if len(unc) > 5 else "")))
        elif unc:
            warns.append("literature_sources %s: %d record(s) say UNCERTAIN (%s); the coordinator will check them"
                         % (sid, len(unc), ", ".join(unc)))
    return errs, warns


def _rid(tn, r):
    for k, v in r.items():
        if k.endswith("_id") and k != "source_id" or k == "record_id":
            return v
    return "?"


ENVELOPE_RE = re.compile(r"envelope\s*\([+-]\)|cycle\s+(peaks|valleys)", re.I)
CONFINED_RE = re.compile(r"triaxial|biaxial|hydrostatic|(?<!un)confin", re.I)


def physics_checks(fig, db):
    """The curve checks the database runs on every figure after merging (re-implemented here).
    Returns (failures -> marked red, notices -> marked yellow)."""
    fails, warns = [], []
    try:
        curves = json.loads(fig.get("curve_data") or "[]")
    except ValueError:
        return ["curve_data is not valid JSON"], []
    curves = [c for c in curves if isinstance(c, dict) and isinstance(c.get("points"), list) and c["points"]]
    if not curves:
        return fails, warns
    pt = fig.get("plot_type", "")
    xul, yul = fig.get("x_units", "").lower(), fig.get("y_units", "").lower()
    is_ld = pt in ("load_displacement", "load_CMOD", "load_deflection")
    x_strain = xul in ("%", "-", "") or "strain" in xul or "mm/mm" in xul
    y_stress = ("mpa" in yul or "ksi" in yul or "psi" in yul) and "gpa" not in yul
    is_ss = pt == "stress_strain" and x_strain and y_stress
    linked = [s.strip() for s in fig.get("linked_test_ids", "").split(",") if s.strip()]
    test = next((t for t in db.get("tests", []) if linked and t.get("test_id") == linked[0]), None)
    blob = ((test or {}).get("test_type") or "") + " " + (fig.get("caption") or "") + " " + (fig.get("stress_state") or "")
    uni = is_ss and not CONFINED_RE.search(blob)
    batch = None
    if test and test.get("specimen_id"):
        spec = next((s for s in db.get("specimens", []) if s.get("specimen_id") == test["specimen_id"]), None)
        if spec and spec.get("batch_id"):
            batch = next((b for b in db.get("material_batches", []) if b.get("batch_id") == spec["batch_id"]), None)

    def leg(c):
        return c.get("legend") or ""

    def P(c):
        return [(float(p["x"]), float(p["y"])) for p in c["points"]]

    if uni and "mpa" in yul and ("mm/mm" in xul or xul == "%" or "strain" in xul or xul == "-"):
        for c in curves:
            s = sorted(P(c), key=lambda q: q[0])
            if len(s) < 5:
                continue
            pk = 0.0
            for _, y in s:
                if abs(y) > abs(pk):
                    pk = y
            el = []
            for q in s:
                if abs(q[1]) <= abs(pk) * 0.4:
                    el.append(q)
                else:
                    break
            if len(el) >= 3:
                dx = (el[-1][0] - el[0][0]) * (0.01 if xul == "%" else 1)
                if dx > 0:
                    slope = (el[-1][1] - el[0][1]) / dx
                    lo, hi = (35000, 60000) if batch and (batch.get("material_class") or "").lower() == "uhpc" else (10000, 60000)
                    if not lo <= abs(slope) <= hi:
                        fails.append("curve %r: initial (elastic) slope ~%.0f MPa is outside [%d, %d]" % (leg(c), slope, lo, hi))
    if uni:
        for c in curves:
            p = P(c)
            if len(p) < 3:
                continue
            my, px = -math.inf, 0.0
            for x, y in p:
                if abs(y) > my:
                    my, px = abs(y), x
            e = px * (0.01 if xul == "%" else 1)
            if e < 0.0005 or e > 0.01:
                fails.append("curve %r: strain at peak %.4g is outside [0.0005, 0.01]%s" % (
                    leg(c), e, " (write compression as positive strain)" if e < 0 else ""))
    # axis bounds: the stored ones if given, else the data's own range (then no coverage check)
    try:
        b = [float(leading_number(fig.get(k, "")) if leading_number(fig.get(k, "")) is not None else "nan")
             for k in ("x_min", "x_max", "y_min", "y_max")]
    except ValueError:
        b = [math.nan] * 4
    from_data = not (all(math.isfinite(v) for v in b) and b[1] != b[0] and b[3] != b[2])
    if from_data:
        allp = [q for c in curves for q in P(c)]
        b = [min(q[0] for q in allp), max(q[0] for q in allp), min(q[1] for q in allp), max(q[1] for q in allp)]
    xr, yr = abs(b[1] - b[0]), abs(b[3] - b[2])
    if is_ss or is_ld:
        for c in curves:
            x0, y0 = sorted(P(c), key=lambda q: q[0])[0]
            if xr > 0 and yr > 0 and (abs(x0 - b[0]) / xr > 0.1 or abs(y0 - b[2]) / yr > 0.1):
                warns.append("curve %r: first point (%.3g, %.3g) is far from the origin" % (leg(c), x0, y0))
    if uni:
        for c in curves:
            s = sorted(P(c), key=lambda q: q[0])
            if len(s) < 5:
                continue
            pk = 0.0
            for _, y in s:
                if abs(y) > abs(pk):
                    pk = y
            v = 0
            for k in range(1, len(s)):
                if abs(s[k][1]) > abs(pk) * 0.4:
                    break
                if abs(s[k][1]) < abs(s[k - 1][1]) - 0.01 * abs(pk):
                    v += 1
            if v >= 2:
                fails.append("curve %r: %d drops in the rising (elastic) part of the curve" % (leg(c), v))
    for c in curves:
        n = len(c["points"])
        if 0 < n < 8:
            warns.append("curve %r: only %d points (the database flags under 8 for review)" % (leg(c), n))
        if n > 150:
            warns.append("curve %r: %d points (the database flags over 150; use --max-points 150)" % (leg(c), n))
    if xr > 0:
        need = 0.35 if pt.lower() in ("load_cmod", "force_drift") else 0.50
        for c in curves:
            s = sorted(q[0] for q in P(c))
            if len(s) < 10 or ENVELOPE_RE.search(leg(c)):
                continue
            if not from_data and (s[-1] - s[0]) / xr < need:
                fails.append("curve %r covers %.0f%% of the x axis (x_min..x_max); the database needs %.0f%%. "
                             "Check x_min/x_max are the plotted axis range and the whole curve was traced"
                             % (leg(c), (s[-1] - s[0]) / xr * 100, need * 100))
            gap = max(b2 - a2 for a2, b2 in zip(s[:-1], s[1:]))
            if gap / xr > 0.20:
                fails.append("curve %r has an x-gap of %.0f%% of the x axis (over 20%%): a stretch of curve was "
                             "missed; check the overlay" % (leg(c), gap / xr * 100))
    return fails, warns


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("draft")
    ap.add_argument("out_dir")
    ap.add_argument("--formats", default="json,csv,xlsx")
    ap.add_argument("--allow-dangling", action="store_true")
    ap.add_argument("--correction", action="store_true", help="allow this paper's title/DOI to change")
    ap.add_argument("--sent", action="store_true", help="record this build as the version sent to the coordinator")
    a = ap.parse_args(argv)
    formats = {s.strip() for s in a.formats.split(",") if s.strip()}
    bad = formats - {"json", "csv", "xlsx"}
    if bad:
        print("unknown format(s): " + ", ".join(sorted(bad)), file=sys.stderr)
        return 2
    formats.add("json")  # the JSON is the file the coordinator merges; always written
    try:
        with open(a.draft, encoding="utf-8") as f:
            draft = json.load(f)
    except OSError as e:
        print("cannot read the draft %s: %s" % (a.draft, e.strerror), file=sys.stderr)
        return 1
    except ValueError as e:
        print("the draft %s is not valid JSON: %s" % (a.draft, e), file=sys.stderr)
        return 1
    try:
        os.makedirs(a.out_dir, exist_ok=True)
        db, state, state_path, changed, removed, warnings = build(draft, a.out_dir, a.allow_dangling, a.correction)
        additions = None
        if state.get("sent_at_build") and not a.sent:
            sent_ids = set(state["sent_ids"])
            tables = load_schema()["tables"]
            additions = {t: [r for r in rows if tables[t]["prefix"] and r.get(tables[t]["id"]) not in sent_ids]
                         for t, rows in db.items()}
            new_src = {r["source_id"] for r in additions.get("literature_sources", [])}
            additions["keywords"] = [r for r in db.get("keywords", []) if r.get("source_id") in new_src]
            if not any(additions.values()):
                additions = None
        if a.sent:
            state["baseline"] = dict(state["fingerprints"])
            state["sent_ids"] = sorted(state["fingerprints"])
            state["sent_at_build"] = True
            changed, removed = [], []
        written = write_outputs(db, load_schema(), a.out_dir, formats, state, state_path, additions)
    except BuildError as e:
        print(str(e), file=sys.stderr)
        return 1
    except OSError as e:
        print("Build stopped while writing files (%s). The files from the previous build were left as they "
              "were; fix the problem (file open in Excel? disk full?) and rerun." % e, file=sys.stderr)
        return 1
    counts = ", ".join("%s %d" % (t, len(r)) for t, r in db.items() if r)
    print("Built: " + counts)
    if changed or removed:
        base = "the version marked sent" if state.get("sent_at_build") else "the first build"
        if changed:
            print("NOTE: %d record(s) changed since %s:" % (len(changed), base))
            for c in changed[:20]:
                print("  " + c)
        if removed:
            print("NOTE: %d record(s) from %s are no longer in this build (deleted, or their @key was "
                  "renamed):" % (len(removed), base))
            for c in removed[:20]:
                print("  " + c)
        print("If the coordinator already has the earlier file, tell them this is a CORRECTION (the database "
              "refuses a record it already has with different content, and keeps removed ones). After you "
              "send this file, rerun with --sent.")
    for p in written:
        print("  wrote " + p)
    if additions is not None:
        print("  concrete_database_additions.json holds only the records added since the sent version: "
              "send that one if the earlier file was already merged and nothing in it changed.")
    for w in warnings:
        print("WARNING: " + w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
