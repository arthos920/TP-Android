failed_kw = BuiltIn().get_variable_value("${FAILED_KEYWORD}", "")
failed_msg = BuiltIn().get_variable_value("${FAILED_MESSAGE}", "")

html_block = f"""
<div style="
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;
  border:1px solid #ececec;
  border-radius:12px;
  background:#ffffff;
  padding:14px;
  margin:12px 0;
  max-width:980px;
  box-shadow:0 8px 22px rgba(0,0,0,0.10);
">

  <!-- Header -->
  <div style="
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:12px;
    margin-bottom:12px;
  ">
    <div style="display:flex; align-items:center; gap:10px; min-width:0;">
      <span style="
        background:#d9534f;
        color:#fff;
        font-weight:900;
        font-size:12px;
        padding:5px 10px;
        border-radius:999px;
        letter-spacing:.6px;
      ">FAIL</span>

      <div style="min-width:0;">
        <div style="color:#111; font-weight:800; font-size:14px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
          {title}
        </div>
        <div style="color:#6b7280; font-size:12px; margin-top:2px;">
          Automated QA evidence
        </div>
      </div>
    </div>

    <span style="
      background:#f3f4f6;
      color:#374151;
      font-size:12px;
      padding:5px 10px;
      border-radius:999px;
      border:1px solid #e5e7eb;
      white-space:nowrap;
    ">📸 Screenshot</span>
  </div>

  <!-- Body (stable layout) -->
  <div style="
    display:grid;
    grid-template-columns: 1fr 360px;
    gap:14px;
    align-items:start;
  ">

    <!-- Left: QA details -->
    <div style="
      border:1px solid #f0f0f0;
      border-radius:12px;
      padding:12px;
      background:#fbfbfb;
    ">

      <!-- Row: Test -->
      <div style="display:flex; gap:10px; align-items:flex-start; margin-bottom:10px;">
        <div style="
          background:#eef6ff;
          border:1px solid #d7ebff;
          color:#0b5ed7;
          font-weight:900;
          font-size:12px;
          padding:6px 10px;
          border-radius:10px;
          white-space:nowrap;
        ">🧪 TEST</div>

        <div style="
          color:#111827;
          font-size:13px;
          font-weight:800;
          line-height:1.25;
          word-break:break-word;
        ">{test_name}</div>
      </div>

      <!-- Row: Keyword (optional) -->
      {f'''
      <div style="display:flex; gap:10px; align-items:flex-start; margin-bottom:10px;">
        <div style="
          background:#fff7ed;
          border:1px solid #ffe1bf;
          color:#9a3412;
          font-weight:900;
          font-size:12px;
          padding:6px 10px;
          border-radius:10px;
          white-space:nowrap;
        ">⚙️ KW</div>

        <div style="
          color:#374151;
          font-size:12.5px;
          font-weight:800;
          line-height:1.25;
          word-break:break-word;
        ">{failed_kw}</div>
      </div>
      ''' if failed_kw else ''}

      <!-- Failure details (optional) -->
      {f'''
      <div style="
        border:1px solid #f3c7c6;
        background:#fff5f5;
        border-radius:12px;
        padding:10px;
        margin-top:8px;
      ">
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:6px;">
          <span style="width:10px; height:10px; border-radius:50%; background:#d9534f; display:inline-block;"></span>
          <span style="font-weight:950; color:#b02a37; font-size:12px;">Failure details</span>
        </div>

        <div style="
          color:#7a1f2b;
          font-size:12px;
          line-height:1.35;
          white-space:pre-wrap;
          word-break:break-word;
        ">{failed_msg}</div>
      </div>
      ''' if failed_msg else ''}

      <!-- Tags -->
      <div style="margin-top:12px; display:flex; gap:8px; flex-wrap:wrap;">
        <span style="background:#fff; border:1px solid #e5e7eb; color:#6b7280; font-size:11px; padding:4px 8px; border-radius:999px;">Robot Log</span>
        <span style="background:#fff; border:1px solid #e5e7eb; color:#6b7280; font-size:11px; padding:4px 8px; border-radius:999px;">Mobile</span>
        <span style="background:#fff; border:1px solid #e5e7eb; color:#6b7280; font-size:11px; padding:4px 8px; border-radius:999px;">Evidence</span>
      </div>
    </div>

    <!-- Right: Screenshot -->
    <div style="
      border:1px solid #f0f0f0;
      border-radius:12px;
      padding:12px;
      background:#ffffff;
      text-align:center;
    ">
      <a href="{rel_path}" style="text-decoration:none;">
        <img src="{rel_path}" style="
          width:340px;
          max-width:100%;
          border-radius:12px;
          border:1px solid #e6e6e6;
          box-shadow:0 12px 28px rgba(0,0,0,0.14);
          transition:transform .15s ease, box-shadow .15s ease;
        "
        onmouseover="this.style.transform='translateY(-2px)'; this.style.boxShadow='0 16px 36px rgba(0,0,0,0.18)';"
        onmouseout="this.style.transform='translateY(0)'; this.style.boxShadow='0 12px 28px rgba(0,0,0,0.14)';"
        >
      </a>

      <div style="margin-top:10px;">
        <a href="{rel_path}" style="
          display:inline-block;
          background:#111827;
          color:#fff;
          font-weight:900;
          font-size:12px;
          padding:7px 12px;
          border-radius:999px;
          text-decoration:none;
        ">🔍 Open full screenshot</a>
      </div>
    </div>

  </div>
</div>
"""