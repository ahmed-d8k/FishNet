import numpy as np
import torch
import torchvision
import matplotlib.pyplot as plt
import cv2
import src.user_interaction as usr_int
import tkinter as tk
from src.nodes.AbstractNode import AbstractNode
from nd2reader import ND2Reader
from segment_anything import sam_model_registry, SamPredictor
import src.image_processing as ip
import src.sam_processing as sp
from PIL import Image, ImageTk

class RectTracker:
    def __init__(self, canvas, gui):
        self.canvas = canvas
        self.gui = gui
        self.item = None
        self.box = None
		
    def draw(self, start, end, **opts):
        return self.canvas.create_rectangle(*(list(start)+list(end)), **opts)
		
    def autodraw(self, **opts):
        """Setup automatic drawing; supports command option"""
        self.start = None
        self.canvas.bind("<Button-1>", self.__update, '+')
        self.canvas.bind("<B1-Motion>", self.__update, '+')
        self.canvas.bind("<ButtonRelease-1>", self.__stop, '+')
        self._command = opts.pop('command', lambda *args: None)
        self.rectopts = opts

    def __update(self, event):
        if not self.start:
            self.start = [event.x, event.y]
            return
        if self.item is not None:
            self.canvas.delete(self.item)
        self.item = self.draw(self.start, (event.x, event.y), **self.rectopts)
        self._command(self.start, (event.x, event.y))
	
    def __stop(self, event):
        self.start = None
        self.canvas.delete(self.item)
        self.item = None
        self.give_final_box()

    def give_final_box(self):
        self.gui.segment_box(self.box)
	
    def get_box(self, start, end, tags=None, ignoretags=None, ignore=[]):
        xlow = min(start[0], end[0])
        xhigh = max(start[0], end[0])
	
        ylow = min(start[1], end[1])
        yhigh = max(start[1], end[1])
	
        self.box = [xlow, ylow, xhigh, yhigh]

class MSSGui():
    def __init__(self, owner):
        self.master_node = owner
        self.root = tk.Tk()
        self.root.geometry("600x600")
        self.root.title("Manual Sam Segmenter")

        img_arr = np.zeros((512,512,3)).astype(np.uint8)
        self.curr_img =  ImageTk.PhotoImage(image=Image.fromarray(img_arr))
        self.canvas = tk.Canvas(self.root, width=512, height=512)
        self.canvas.pack()
        self.rect = RectTracker(self.canvas, self)
        def on_drag(start, end):
            self.rect.get_box(start, end)
        self.rect.autodraw(fill="", width=2, command=on_drag)
        
        self.img_container = self.canvas.create_image(0, 0, anchor="nw", image=self.curr_img)

        self.button_frame = tk.Frame(self.root)
        self.button_frame.columnconfigure(0, weight=1)
        self.button_frame.columnconfigure(1, weight=1)
        self.button_frame.columnconfigure(2, weight=1)

        self.done_button = tk.Button(self.button_frame, text="Done")
        self.done_button.grid(row=0, column=0, sticky=tk.W+tk.E)

        self.reset_button = tk.Button(self.button_frame, text="Reset")
        self.reset_button.grid(row=0, column=1, sticky=tk.W+tk.E)

        self.quit_button = tk.Button(self.button_frame,
                                     text="Quit",
                                     command=self.quit)
        self.quit_button.grid(row=0, column=2, sticky=tk.W+tk.E)

        self.button_frame.pack(fill='x')

    def quit(self):
        self.master_node.hello_world()

    def segment_box(self, box):
        self.master_node.updates_boxes(box)
        img_arr = self.master_node.process_img()
        self.update_img(img_arr)

    def run(self):
        self.root.mainloop()

    def update_img(self, img_arr):
        img_arr = img_arr.astype(np.uint8)
        self.curr_img =  ImageTk.PhotoImage(image=Image.fromarray(img_arr))
        self.canvas.itemconfig(self.img_container, image=self.curr_img)
        # self.canvas.create_image(20, 20, anchor="nw", image=self.curr_img)
        print("Hello??")


class ManualSamSegmenter(AbstractNode):
    def __init__(self):
        super().__init__(output_name="NucleusMask",
                         requirements=[],
                         user_can_retry=False,
                         node_title="Manual SAM Segmenter")
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.sam_mask_generator = None
        self.sam = None
        self.sam_predictor = None
        self.input_boxes = []
        self.input_points = [[0,0]]
        self.input_labels = [0]
        self.gui = None
        self.prepared_img = None
        self.curr_img = None

    def setup_sam(self):
        sam_checkpoint = "sam_model/sam_vit_h_4b8939.pth"
        model_type = "vit_h"
        self.sam = sam_model_registry[model_type](checkpoint=sam_checkpoint)
        self.sam.to(device=self.device)
        self.sam_predictor = SamPredictor(self.sam)
        self.sam_predictor.set_image(self.prepared_img)

    def gui_update_img(self):
        self.gui.update_img(self.curr_img)

    def updates_boxes(self, box):
        self.input_boxes.append(box)

    def process_img(self):
        sam_masks = self.apply_sam_pred()
        print(sam_masks.shape)
        mask_img = np.where(sam_masks == True, 1, 0)[0,:,:].astype(np.uint8)
        # mask_3d = np.where(sam_masks == True, 255, 0)[0,:,:].astype(np.uint8)
        # mask_3d = cv2.cvtColor(mask_3d, cv2.COLOR_GRAY2BGR)
        # mask_img = sp.generate_mask_img(self.prepared_img, sam_masks)
        contour_img = ip.generate_contour_img(mask_img)
        anti_ctr = ip.generate_anti_contour(contour_img).astype(np.uint8)
        # act_mask = ip.generate_activation_mask(mask_img)
        self.curr_img = self.prepared_img.astype(np.uint8)
        self.curr_img *= anti_ctr
        self.curr_img += contour_img

        # self.curr_img = self.prepared_img.astype(np.uint8)
        # print(mask_3d.shape)
        # self.curr_img *= mask_3d
        return self.curr_img

    def apply_sam_pred(self):
        arr_boxes = np.array(self.input_boxes)
        arr_points = np.array(self.input_points)
        arr_labels = np.array(self.input_labels)
        print(self.input_boxes)
        masks, _, _ = self.sam_predictor.predict(
            point_coords=arr_points,
            point_labels=arr_labels,
            box=arr_boxes,
            multimask_output=False)
        return masks

    def process(self):
        self.gui.run()
        pass

    def hello_world(self):
        print("Hello World")

    def initialize_node(self):
        raw_img = ip.get_raw_nucleus_img()
        self.prepared_img = ip.preprocess_img(raw_img)
        self.gui = MSSGui(self)
        self.gui.update_img(self.prepared_img)
        self.setup_sam()

    def plot_output(self):
        pass