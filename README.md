failed_kw = BuiltIn().get_variable_value("${FAILED_KEYWORD}", "")
failed_msg = BuiltIn().get_variable_value("${FAILED_MESSAGE}", "")

html_block = f"""
<div style="
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;
  border:1px solid #ececec;
  border-radius:14px;
  background:#ffffff;
  padding:14px;
  margin:12px 0;
  max-width:980px;
  box-shadow:0 10px 26px rgba(0,0,0,0.10);
">

  <div style="
    display:grid;
    grid-template-columns: 1fr 420px;
    gap:14px;
    align-items:stretch;
  ">

    <!-- LEFT COLUMN (stacked cards) -->
    <div style="
      display:grid;
      grid-template-rows:auto auto 1fr;
      gap:12px;
      min-width:320px;
    ">

      <!-- CARD: TITLE -->
      <div style="
        border:1px solid #f0f0f0;
        background:#fbfbfb;
        border-radius:12px;
        padding:12px;
      ">
        <div style="display:flex; align-items:center; gap:10px;">
          <span style="
            background:#d9534f;
            color:#fff;
            font-weight:900;
            font-size:12px;
            padding:5px 10px;
            border-radius:999px;
            letter-spacing:.6px;
          ">FAIL</span>

          <div style="
            color:#111;
            font-weight:900;
            font-size:14px;
            line-height:1.25;
            word-break:break-word;
          ">{title}</div>
        </div>

        <div style="
          margin-top:8px;
          display:flex;
          gap:8px;
          flex-wrap:wrap;
        ">
          <span style="
            background:#f3f4f6;
            border:1px solid #e5e7eb;
            color:#6b7280;
            font-size:11px;
            padding:4px 8px;
            border-radius:999px;
          ">Robot Log</span>
          <span style="
            background:#f3f4f6;
            border:1px solid #e5e7eb;
            color:#6b7280;
            font-size:11px;
            padding:4px 8px;
            border-radius:999px;
          ">Evidence</span>
          <span style="
            background:#f3f4f6;
            border:1px solid #e5e7eb;
            color:#6b7280;
            font-size:11px;
            padding:4px 8px;
            border-radius:999px;
          ">Mobile</span>
        </div>
      </div>

      <!-- CARD: TEST -->
      <div style="
        border:1px solid #f0f0f0;
        background:#fbfbfb;
        border-radius:12px;
        padding:12px;
      ">
        <div style="display:flex; align-items:flex-start; gap:10px;">
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
            font-weight:900;
            line-height:1.25;
            word-break:break-word;
          ">{test_name}</div>
        </div>

        {f'''
        <div style="margin-top:10px; display:flex; align-items:flex-start; gap:10px;">
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

      </div>

      <!-- CARD: FAILURE DETAILS (fills remaining height if present) -->
      {f'''
      <div style="
        border:1px solid #f3c7c6;
        background:#fff5f5;
        border-radius:12px;
        padding:12px;
        display:flex;
        flex-direction:column;
      ">
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">
          <span style="width:10px; height:10px; border-radius:50%; background:#d9534f; display:inline-block;"></span>
          <span style="font-weight:950; color:#b02a37; font-size:12px;">Failure details</span>
        </div>

        <div style="
          color:#7a1f2b;
          font-size:12px;
          line-height:1.35;
          white-space:pre-wrap;
          word-break:break-word;
          overflow:auto;
          max-height:220px;
        ">{failed_msg}</div>
      </div>
      ''' if failed_msg else '<div></div>'}

    </div>

    <!-- RIGHT COLUMN (big image) -->
    <div style="
      border:1px solid #f0f0f0;
      border-radius:12px;
      background:#ffffff;
      padding:12px;
      display:flex;
      flex-direction:column;
      justify-content:center;
      align-items:center;
      text-align:center;
    ">

      <div style="
        display:flex;
        align-items:center;
        justify-content:space-between;
        width:100%;
        margin-bottom:10px;
      ">
        <span style="
          background:#f3f4f6;
          border:1px solid #e5e7eb;
          color:#374151;
          font-size:12px;
          padding:5px 10px;
          border-radius:999px;
        ">📸 Screenshot</span>

        <a href="{rel_path}" style="
          text-decoration:none;
          background:#111827;
          color:#fff;
          font-weight:900;
          font-size:12px;
          padding:7px 12px;
          border-radius:999px;
        ">🔍 Open</a>
      </div>

      <a href="{rel_path}" style="text-decoration:none;">
        <img src="{rel_path}" style="
          width:380px;
          max-width:100%;
          border-radius:12px;
          border:1px solid #e6e6e6;
          box-shadow:0 14px 34px rgba(0,0,0,0.16);
          transition:transform .15s ease, box-shadow .15s ease;
        "
        onmouseover="this.style.transform='translateY(-2px)'; this.style.boxShadow='0 18px 42px rgba(0,0,0,0.20)';"
        onmouseout="this.style.transform='translateY(0)'; this.style.boxShadow='0 14px 34px rgba(0,0,0,0.16)';"
        >
      </a>

      <div style="margin-top:10px; color:#6b7280; font-size:11px;">
        Click the image to open full resolution.
      </div>
    </div>

  </div>
</div>
"""