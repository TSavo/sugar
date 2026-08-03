def row_identity:
  [
    .owner,
    .file,
    (.coordinate | tostring),
    .observed,
    .requested,
    .entrance
  ];

def file_start:
  . as $row
  | if (($row.coordinate | tostring) | test("start_line=[0-9]+")) then
      ($row.file + ":" + (($row.coordinate | tostring) | capture("start_line=(?<line>[0-9]+)").line))
    elif (($row.coordinate | tostring) | test(":" + "[0-9]+" + ":")) then
      ($row.file + ":" + (($row.coordinate | tostring) | capture(":(?<line>[0-9]+):").line))
    else
      ($row.file + ":" + ($row.coordinate | tostring))
    end;

def deliberate_membrane:
  .owner == "With._construct_sugar"
  and (.observed | contains("call-target-off-population"))
  and (
    (.observed | contains("distribution 'pytest'"))
    or (.observed | contains("stdlib module"))
  );

def landed_defect:
  .owner == "With._construct_sugar"
  and (.observed | contains("call-target-off-population"))
  and (.observed | contains("distribution 'pandas'"));

def boundary_early_manifest:
  [
    "conftest.py:2151",
    "tests/arithmetic/test_numeric.py:35",
    "tests/arrays/categorical/test_indexing.py:377",
    "tests/config/test_config.py:15",
    "tests/config/test_localization.py:97",
    "tests/extension/test_numpy.py:71",
    "tests/frame/test_arithmetic.py:51",
    "tests/frame/test_stack_unstack.py:2293",
    "tests/generic/test_frame.py:106",
    "tests/generic/test_series.py:110",
    "tests/indexes/datetimes/test_iter.py:71",
    "tests/indexes/multi/test_duplicates.py:263",
    "tests/indexes/multi/test_integrity.py:131",
    "tests/io/formats/test_console.py:36",
    "tests/io/parser/dtypes/test_categorical.py:128",
    "tests/io/parser/test_index_col.py:255",
    "tests/io/test_clipboard.py:107",
    "tests/io/test_gcs.py:103",
    "tests/reshape/test_pivot.py:2152",
    "tests/series/methods/test_isin.py:207",
    "tests/series/test_arithmetic.py:36",
    "tests/test_expressions.py:138",
    "tests/test_nanops.py:23",

    "_version.py:159",
    "core/series.py:1573",
    "tests/frame/methods/test_to_csv.py:730",
    "tests/io/conftest.py:141",
    "tests/io/formats/style/test_html.py:64",
    "tests/io/formats/test_to_csv.py:34",
    "tests/io/formats/test_to_html.py:49",
    "tests/io/formats/test_to_latex.py:34",
    "tests/io/generate_legacy_storage_files.py:361",
    "tests/io/json/test_pandas.py:1482",
    "tests/io/parser/common/test_common_basic.py:864",
    "tests/io/parser/common/test_file_buffer_url.py:429",
    "tests/io/parser/test_compression.py:30",
    "tests/io/parser/test_encoding.py:66",
    "tests/io/parser/test_network.py:45",
    "tests/io/parser/test_python_parser_only.py:167",
    "tests/io/parser/test_read_fwf.py:679",
    "tests/io/parser/test_textreader.py:40",
    "tests/io/sas/test_sas7bdat.py:59",
    "tests/io/test_feather.py:164",
    "tests/io/test_html.py:217",
    "tests/io/test_iceberg.py:51",
    "tests/io/test_parquet.py:701",
    "tests/io/xml/test_to_xml.py:997",
    "tests/io/xml/test_xml_dtypes.py:35",
    "tests/series/methods/test_to_csv.py:57",
    "tests/util/test_show_versions.py:19",
    "util/_print_versions.py:148",

    "core/base.py:1643",
    "core/window/rolling.py:589",
    "tests/frame/test_npfuncs.py:23",
    "tests/frame/methods/test_info.py:193",
    "tests/io/parser/test_c_parser_only.py:304",
    "tests/io/pytables/test_compat.py:37",
    "tests/io/pytables/test_keys.py:46",
    "io/formats/xml.py:553",
    "io/xml.py:537",
    "tests/plotting/frame/test_frame_subplots.py:556",
    "tests/plotting/test_datetimelike.py:1692",

    "plotting/_matplotlib/__init__.py:67",
    "tests/plotting/test_style.py:25",
    "_testing/__init__.py:541",
    "tests/io/test_fsspec.py:76",
    "tests/io/test_sql.py:877",
    "_testing/_io.py:128",
    "tests/io/test_common.py:92",
    "tests/io/test_pickle.py:297"
  ];

def existing_construct_wrong_entrance_manifest:
  [
    "tests/io/parser/common/test_chunksize.py:53",
    "tests/io/parser/common/test_iterator.py:42",
    "io/formats/format.py:1044",
    "io/sql.py:354",
    "io/common.py:405"
  ];

def matching_classes:
  . as $row
  | [
      if deliberate_membrane then "deliberate-membrane" else empty end,
      if landed_defect then "landed-defect" else empty end,
      if (boundary_early_manifest | index($row | file_start)) != null
        then "boundary-exposure-terminating-early" else empty end,
      if (existing_construct_wrong_entrance_manifest | index($row | file_start)) != null
        then "existing-construct-behind-wrong-entrance" else empty end,
      if .owner == "populate_same_module_class_manager"
        then "entrance-defect" else empty end,
      if .owner == "roll_call.discharge"
        and (.observed | startswith("RecursionError while constructing"))
        then "engine-invariant" else empty end
    ];

def class_name:
  matching_classes as $classes
  | if ($classes | length) == 1 then $classes[0]
    elif ($classes | length) == 0 then "uncovered"
    else "multiply-classified"
    end;

. as $receipt
| ($receipt.constructionPanics | map(. + {
    rowIdentity: row_identity,
    fileStart: file_start,
    matchingClasses: matching_classes,
    closingClass: class_name
  })) as $rows
| {
    schema: "sugar.frontier-closing-account.v1",
    sourceReceipt: {
      sha256: "cedb430388de1bd85b8bddcdc4d547a8dfcba3954e00e8930d8419bc936274b4",
      measuredCommit: $receipt.measuredCommit,
      frontierWidth: $receipt.frontierWidth,
      denominator: $receipt.denominator
    },
    caveats: [
      "477 is a FIRST-TERMINAL LOWER BOUND.",
      "Descendants behind each first terminal remain masked.",
      "944/1421 is attendance testimony, not completion.",
      "Files-unblocked means the current first terminal MOVES; it does not mean the file completes or remaining work falls by that count."
    ],
    selectors: {
      deliberateMembrane: "owner == With._construct_sugar AND observed contains call-target-off-population AND (distribution pytest OR stdlib module)",
      landedDefect: "owner == With._construct_sugar AND observed contains call-target-off-population AND distribution pandas; fixed after the measured commit by #7227/25d1dc7d02e75275117d2b958721c299f0d50062",
      boundaryExposureTerminatingEarly: {
        rule: "exact file:start membership after normalizing the source coordinate; every member terminates before the population predicate and counterfactually belongs outside enrolled pandas",
        manifest: boundary_early_manifest
      },
      existingConstructBehindWrongEntrance: {
        rule: "exact file:start membership; source construction exists but the current entrance cannot reach it",
        manifest: existing_construct_wrong_entrance_manifest
      },
      entranceDefect: "owner == populate_same_module_class_manager",
      engineInvariant: "owner == roll_call.discharge AND observed starts with RecursionError while constructing"
    },
    classCounts: (
      $rows
      | group_by(.closingClass)
      | map({key: .[0].closingClass, value: length})
      | from_entries
    ),
    accountedCount: ($rows | map(select(.closingClass != "uncovered")) | length),
    uncoveredCount: ($rows | map(select(.closingClass == "uncovered")) | length),
    uncoveredRows: ($rows | map(select(.closingClass == "uncovered") | {
      rowIdentity, fileStart, owner, coordinate, observed, requested, entrance
    })),
    multiplyClassifiedCount: ($rows | map(select(.closingClass == "multiply-classified")) | length),
    multiplyClassifiedRows: ($rows | map(select(.closingClass == "multiply-classified") | {
      rowIdentity, fileStart, matchingClasses, owner, coordinate, observed, requested, entrance
    })),
    duplicateRowIdentities: (
      $rows
      | group_by(.rowIdentity)
      | map(select(length > 1) | {rowIdentity: .[0].rowIdentity, count: length})
    ),
    rowsByClass: (
      $rows
      | group_by(.closingClass)
      | map({
          key: .[0].closingClass,
          value: map({
            rowIdentity,
            fileStart,
            owner,
            coordinate,
            observed,
            requested,
            entrance
          })
        })
      | from_entries
    )
  }
