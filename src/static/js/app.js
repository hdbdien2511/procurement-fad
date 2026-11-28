// Tăng cường tuỳ chọn; trang vẫn dùng được đầy đủ khi không có JavaScript.
document.addEventListener("change", function (e) {
  var t = e.target;
  if (t && t.matches && t.matches("input[data-select-all]")) {
    var table = t.closest("table");
    if (table) table.querySelectorAll('input[name="ids"]').forEach(function (c) { c.checked = t.checked; });
  }
});
