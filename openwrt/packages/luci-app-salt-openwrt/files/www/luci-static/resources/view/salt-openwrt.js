'use strict';
'require view';
'require form';

return view.extend({
	render: function () {
		var m, s, o;

		m = new form.Map('salt-openwrt', _('Salt Agent'),
			_('Configure how Salt manages this device. ' +
			  'The Salt state module reads this configuration at the start ' +
			  'of every run to determine its behavior.'));

		s = m.section(form.NamedSection, 'global', 'salt-openwrt',
			_('Agent Settings'));

		o = s.option(form.Flag, 'enabled', _('Enable Salt management'),
			_('When disabled, Salt skips this device entirely. ' +
			  'No configuration is read, no changes are made.'));
		o.rmempty = false;
		o.default = '1';

		o = s.option(form.ListValue, 'mode', _('Operating mode'),
			_('Controls what Salt is allowed to do on this device.'));
		o.value('audit', _('Audit') + ' -- ' +
			_('Read-only. Salt reports configuration drift but makes no changes.'));
		o.value('oneshot', _('Oneshot') + ' -- ' +
			_('Full automation. Salt stages, applies, verifies, and confirms in one run.'));
		o.value('autoverified', _('Autoverified') + ' -- ' +
			_('Salt stages changes in one run. A separate applied() state activates them ' +
			  'with rollback protection.'));
		o.value('humanreviewed', _('Human-reviewed') + ' -- ' +
			_('Reserved for future LuCI approval gate. Currently behaves like autoverified.'));
		o.default = 'audit';

		o = s.option(form.Value, 'rollback_timeout', _('Rollback timeout (seconds)'),
			_('Seconds to wait before auto-reverting unapplied changes. ' +
			  'Used by oneshot mode and the applied() state.'));
		o.datatype = 'uinteger';
		o.default = '120';

		o = s.option(form.DummyValue, 'last_run', _('Last state run'));
		o.placeholder = _('No data');

		o = s.option(form.DummyValue, 'last_drift', _('Last drift detected'));
		o.placeholder = _('No data');

		return m.render();
	}
});
