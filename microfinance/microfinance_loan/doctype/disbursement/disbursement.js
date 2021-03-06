// Copyright (c) 2017, Libermatic and contributors
// For license information, please see license.txt

function calculate_total(frm) {
  const { amount = 0, recovered_amount = 0 } = frm.doc;
  frm.set_value('total', amount - recovered_amount);
}

function calculate_extra_charges(frm) {
  const { loan_charges = [] } = frm.doc;
  frm.set_value(
    'extra_charges',
    loan_charges.reduce((a, { charge_amount: x = 0 }) => a + x, 0)
  );
}

async function toggle_cheque_fields(frm) {
  const { payment_account } = frm.doc;
  if (payment_account) {
    const { message } = await frappe.db.get_value(
      'Account',
      payment_account,
      'account_type'
    );
    const show_field = message['account_type'] === 'Bank';
    frm.toggle_display(['cheque_no', 'cheque_date'], show_field);
    frm.toggle_reqd(['cheque_no', 'cheque_date'], show_field);
  }
}

frappe.ui.form.on('Disbursement', {
  validate: function(frm) {
    if (!frm.doc['total']) {
      frappe.throw('Cannot do transaction of zero values.');
    }
  },
  refresh: function(frm) {
    frm.fields_dict['loan'].get_query = doc => ({
      filters: { docstatus: 1 },
    });
    frappe.ui.form.on('Other Loan Charge', {
      charge_amount: calculate_extra_charges,
      loan_charges_remove: calculate_extra_charges,
    });
    if (frm.doc.docstatus > 0 && !frm.doc['recovered_partially']) {
      frm.set_df_property('recovered_partially', 'hidden', 1);
    }
  },
  onload: async function(frm) {
    if (frm.doc.__islocal) {
      const { message } = await frappe.db.get_value('Loan Settings', null, [
        'mode_of_payment',
      ]);
      if (message) {
        const { mode_of_payment, loan_account } = message;
        frm.set_value('mode_of_payment', mode_of_payment);
      }
    }
    toggle_cheque_fields(frm);
  },
  loan: async function(frm) {
    const { loan } = frm.doc;
    const [{ message = {} }, { message: amount = 0 }] = await Promise.all([
      frappe.db.get_value('Loan', frm.doc['loan'], 'customer'),
      frappe.call({
        method:
          'microfinance.microfinance_loan.doctype.loan.loan.get_undisbursed_principal',
        args: { loan },
      }),
    ]);
    frm.set_value('customer', message['customer']);
    frm.set_value('amount', amount);
  },
  amount: calculate_total,
  recovered_amount: calculate_total,
  recovered_partially: function(frm) {
    if (!frm.doc['recovered_partially']) {
      frm.set_value('recovered_amount', null);
    }
  },
  mode_of_payment: async function(frm) {
    const { message } = await frappe.call({
      method:
        'erpnext.accounts.doctype.sales_invoice.sales_invoice.get_bank_cash_account',
      args: {
        mode_of_payment: frm.doc.mode_of_payment,
        company: frm.doc.company,
      },
    });
    if (message) {
      frm.set_value('payment_account', message.account);
    }
  },
  payment_account: toggle_cheque_fields,
  onsubmit: function(frm) {
    calculate_total(frm);
    calculate_extra_charges(frm);
  },
});
