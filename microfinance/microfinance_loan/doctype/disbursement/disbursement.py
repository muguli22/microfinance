# -*- coding: utf-8 -*-
# Copyright (c) 2017, Libermatic and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from erpnext.controllers.accounts_controller import AccountsController

from microfinance.microfinance_loan.doctype.loan.loan import get_undisbursed_principal

class Disbursement(AccountsController):
	def validate(self):
		if self.amount > get_undisbursed_principal(self.loan):
			frappe.throw(_("Disbursed amount cannot be greater than sanctioned amount"))
	def on_submit(self):
		self.journal_entry = self.make_jv_entry()
		self.save()
		self.update_loan_status()

	def on_cancel(self):
		pass

	def make_jv_entry(self):
		self.check_permission('write')
		je = frappe.new_doc('Journal Entry')
		je.title = self.customer
		if self.mode_of_payment == 'Cash':
			je.voucher_type = 'Cash Entry'
		elif self.mode_of_payment in ['Cheque', 'Bank Draft', 'Wire Transfer']:
			je.voucher_type = 'Bank Entry'
			je.cheque_no = self.cheque_no
			je.cheque_date = self.cheque_date
		elif self.mode_of_payment == 'Credit Card':
			je.voucher_type = 'Credit Card Entry'
		else:
			je.voucher_type = 'Journal Entry'
		je.user_remark = _('Against Loan: {0}. Disbursement Doc: {1}').format(self.loan, self.name)
		je.company = self.company
		je.posting_date = self.posting_date
		account_amt_list = []
		account_amt_list.append({
				'account': self.loan_account,
				'debit_in_account_currency': self.amount,
				'reference_type': 'Loan',
				'reference_name': self.loan,
			})
		account_amt_list.append({
				'account': self.payment_account,
				'credit_in_account_currency': self.amount,
				'reference_type': 'Loan',
				'reference_name': self.loan,
				'transaction_details': 'Disbursement'
			})
		je.set("accounts", account_amt_list)
		je.insert()
		je.submit()
		return je.name

	def update_loan_status(self):
		'''Method to update disbursement_status of Loan'''
		loan_principal, disbursement_status = frappe.get_value(
				'Loan',
				self.loan,
				['loan_principal', 'disbursement_status']
			)
		undisbursed_principal = get_undisbursed_principal(self.loan)
		if undisbursed_principal <= loan_principal:
			loan = frappe.get_doc('Loan', self.loan)
			if undisbursed_principal > 0:
				if disbursement_status == 'Partially Disbursed':
					return None
				loan.disbursement_status = 'Partially Disbursed'
			else:
				loan.disbursement_status = 'Fully Disbursed'
		return loan.save()
