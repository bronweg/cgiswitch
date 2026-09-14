# Collections Plugins Directory

This directory ships the plugins for the `bronweg.cgiswitch` Ansible
collection. The collection's supported interface is Ansible: the
`jtcom_config` action plugin runs in the controller process, uses
`module_utils` to parse and validate input, and calls the `cgiswitch` Python
library for the JTCom CGI interface. The core library does not use NAPALM.

The module stub in `modules/` provides argument, example, and return
documentation for `ansible-doc`; execution is handled by the action plugin.
The implementation requires ansible-core 2.14.0 or newer and a matching
`cgiswitch` checkout or package in the controller's Python environment. The
collection does not enforce the Python package version at runtime.

This is Alpha software, and hardware validation is pending. CGI behavior can
depend on the installed switch firmware. Applies execute individual writes;
they have no transactional commit or automatic rollback after a failed write.

The collection currently ships these plugin directories:

- `action/`: runs `jtcom_config` in the controller and applies the validated
  desired state through `cgiswitch`.
- `module_utils/`: parses and validates strict Ansible task input and converts
  VLAN and port syntax to the library's canonical model.
- `modules/`: contains the `jtcom_config` module stub used for Ansible
  documentation, examples, and return-value metadata.
