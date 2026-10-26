-- Run from the checkout: nvim --headless -u NONE -l scripts/stress_cancellation.lua
-- Uses only Neovim's built-in LSP client and the checkout's Python environment.
local root = vim.env.ROLS_STRESS_DIR or ('/tmp/rols-cancellation-stress-' .. vim.fn.getpid())
vim.fn.mkdir(root, 'p')
vim.o.hidden = true
vim.cmd('edit ' .. root .. '/sample.py')
vim.bo.filetype = 'python'
vim.api.nvim_buf_set_lines(0, 0, -1, false, { 'import os', 'value = 0', 'os.' })

local server_exited = false
local exit_code
local errors = {}
local normal_responses = 0
local request_ids = {}
local id = assert(vim.lsp.start({
  name = 'rols-cancellation-stress',
  cmd = { vim.env.PYTHON or 'python3', '-m', 'rols', '-v', '--log-file', root .. '/server.log' },
  root_dir = root,
  on_exit = function(code)
    exit_code = code
    server_exited = true
  end,
  settings = {
    rols = {
      plugins = {
        rope_completion = { enabled = true },
        rope_autoimport = { enabled = true },
      },
    },
  },
}))
local client = assert(vim.lsp.get_client_by_id(id))
assert(vim.wait(30000, function() return client.initialized end, 20), 'initialize timed out')

local function completion()
  return {
    textDocument = { uri = vim.uri_from_bufnr(0) },
    position = { line = 2, character = 3 },
  }
end

local function burst()
  for i = 1, 100 do
    vim.api.nvim_buf_set_lines(0, 1, 2, false, { 'value = ' .. i })
    local ok, request_id = client:request('textDocument/completion', completion(), function(err)
      -- Neovim suppresses callbacks for RequestCancelled responses. Request
      -- removal below, rather than callback count, proves acknowledgement.
      normal_responses = normal_responses + 1
      if err then table.insert(errors, vim.inspect(err)) end
    end, 0)
    assert(ok, 'completion request not sent')
    table.insert(request_ids, request_id)
    assert(client:cancel_request(request_id), 'cancellation not sent')
  end
end

burst()
local latest_done = false
local started = vim.uv.hrtime()
assert(client:request('textDocument/completion', completion(), function(err, result)
  if err then table.insert(errors, vim.inspect(err)) end
  if not (result and result.items and #result.items > 0) then
    table.insert(errors, 'final completion is empty')
  end
  latest_done = true
end, 0))
assert(vim.wait(60000, function()
  if not latest_done then return false end
  for _, request_id in ipairs(request_ids) do
    if client.requests[request_id] then return false end
  end
  return true
end, 10), 'backlog did not drain')
local latest_ms = (vim.uv.hrtime() - started) / 1e6

-- Switch documents and verify that another feature still responds.
local other = vim.api.nvim_create_buf(true, false)
vim.api.nvim_buf_set_name(other, root .. '/other.py')
vim.api.nvim_set_current_buf(other)
vim.bo.filetype = 'python'
vim.api.nvim_buf_set_lines(other, 0, -1, false, { 'import os', 'value = 0', 'os.' })
assert(vim.lsp.buf_attach_client(other, id), 'second buffer did not attach')
local hover_done = false
assert(client:request('textDocument/hover', {
  textDocument = { uri = vim.uri_from_bufnr(other) },
  position = { line = 0, character = 8 },
}, function(err, result)
  if err then table.insert(errors, vim.inspect(err)) end
  if not (result and result.contents) then table.insert(errors, 'hover is empty') end
  hover_done = true
end, other))
assert(vim.wait(30000, function() return hover_done end, 10), 'hover timed out')
assert(#errors == 0, table.concat(errors, '\n'))

-- Ask for graceful shutdown with another burst still pending. Wait for the
-- process exit callback, not just for the client to begin stopping.
local acknowledged = #request_ids
local completed_normally = normal_responses
burst()
client:stop(false)
assert(vim.wait(30000, function() return server_exited end, 20), 'server did not stop')
assert(exit_code == 0, 'server exited with code ' .. tostring(exit_code))
assert(#errors == 0, table.concat(errors, '\n'))
print(vim.json.encode({
  acknowledged = acknowledged,
  normal_completion_callbacks = completed_normally,
  latest_ms = latest_ms,
  graceful_exit_code = exit_code,
  log_file = root .. '/server.log',
}))
vim.cmd('qa!')
