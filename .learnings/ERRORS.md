# Errors

Command failures and integration errors.

---

## [ERR-20260918-001] pandas-merge-column-collision

**Logged**: 2026-09-18T15:18:00+08:00
**Priority**: low
**Status**: resolved
**Area**: backend

### Summary
合并 tests.xlsx 与 submission 时，id 类型不一致且 answer 同名列导致查询失败。

### Error
`ValueError: merge on int64 and str columns`；修复类型后又遇到 `KeyError: ['answer'] not in index`。

### Context
- 分析语言题时合并 tests 与 baseline_82。
- 两表均包含 answer，pandas 自动生成 answer_test/answer_sub。

### Suggested Fix
合并前统一 `id.astype(str)`，显式设置 `suffixes=('_test','_sub')`，后续引用 `answer_sub`。

### Metadata
- Reproducible: yes
- Related Files: tests.xlsx, submissions/baseline_82.xlsx

### Resolution
- **Resolved**: 2026-09-18T15:19:00+08:00
- **Notes**: 已统一 id 类型并使用显式后缀。

---
